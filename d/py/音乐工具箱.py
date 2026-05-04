# pip3 install requests
# cmd窗口运行：npx NeteaseCloudMusicApi

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音乐工具箱 - 整合版
功能：
1. 网易云音乐搜索（搜索后自动检测有效性）
2. 外链批量检测
3. M3U格式互转
"""

import os
import re
import sys
import requests
import json
import time
import subprocess  # 用于启动外部程序
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 配置区域 ====================
API_BASE = "http://localhost:3000"
DETECT_TIMEOUT = 10
MAX_WORKERS = 5  # 并发检测线程数

# ==================== 通用函数 ====================
def parse_line(line: str) -> tuple:
    """解析一行文本，返回 (前缀, 外链)"""
    line = line.strip()
    if not line:
        return None, None
    
    if '$' in line:
        parts = line.split('$', 1)
        prefix = parts[0]
        url = parts[1].strip()
        return prefix, url
    else:
        return None, line


def check_url_validity(url: str, check_content_type: bool = True, timeout: int = DETECT_TIMEOUT) -> dict:
    """检测链接是否有效且可播放"""
    if not url.startswith(('http://', 'https://')):
        return {"valid": False, "message": "格式错误：不是有效的HTTP链接", "content_type": ""}
    
    try:
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 405:
                raise Exception("HEAD不支持，降级GET")
        except:
            response = requests.get(url, timeout=timeout, stream=True, allow_redirects=True)
            response.close()
        
        if response.status_code not in [200, 302, 301, 307, 308]:
            return {"valid": False, "message": f"HTTP {response.status_code}", "content_type": ""}
        
        content_type = response.headers.get('Content-Type', '').lower()
        
        if check_content_type:
            audio_types = [
                'audio/mpeg', 'audio/mp4', 'audio/x-m4a', 'audio/flac',
                'audio/x-flac', 'audio/wav', 'audio/x-wav', 'audio/ogg',
                'audio/aac', 'audio/webm', 'application/octet-stream'
            ]
            
            is_audio = any(audio_type in content_type for audio_type in audio_types)
            
            if 'text/html' in content_type:
                return {"valid": False, "message": "返回HTML页面（可能是伪外链）", "content_type": content_type}
            
            if is_audio:
                return {"valid": True, "message": "有效音频", "content_type": content_type}
            else:
                return {"valid": False, "message": f"非音频格式 ({content_type})", "content_type": content_type}
        else:
            return {"valid": True, "message": "有效（HTTP状态码正常）", "content_type": content_type}
            
    except requests.exceptions.Timeout:
        return {"valid": False, "message": "超时", "content_type": ""}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "message": "连接失败", "content_type": ""}
    except Exception as e:
        return {"valid": False, "message": f"请求失败: {str(e)[:50]}", "content_type": ""}


def batch_detect(lines: list, show_progress: bool = True) -> tuple:
    """批量检测链接，返回 (valid_list, invalid_list, stats)"""
    valid = []
    invalid = []
    stats = {"total": len(lines), "valid": 0, "invalid": 0, "html": 0, "error": 0}
    
    if show_progress:
        print(f"\n🔍 开始检测 {len(lines)} 条链接...\n")
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        
        prefix, url = parse_line(line)
        
        if show_progress:
            display = prefix[:40] + "..." if prefix and len(prefix) > 40 else (prefix if prefix else (url[:50] + "..." if url and len(url) > 50 else url))
            print(f"[{i}/{len(lines)}] {display}")
        
        if not url:
            if show_progress:
                print(f"   ⚠️ 格式错误：没有找到链接\n")
            invalid.append({"line": line, "reason": "格式错误：没有找到链接"})
            stats["invalid"] += 1
            stats["error"] += 1
            continue
        
        result = check_url_validity(url, check_content_type=True)
        
        if result["valid"]:
            if show_progress:
                print(f"   ✅ {result['message']}")
                if result.get('content_type'):
                    print(f"   📦 格式: {result['content_type']}")
            valid.append(line)
            stats["valid"] += 1
        else:
            if show_progress:
                print(f"   ❌ {result['message']}")
                if result.get('content_type'):
                    print(f"   📦 实际格式: {result['content_type']}")
            invalid.append({"line": line, "reason": result["message"]})
            stats["invalid"] += 1
            if "HTML" in result["message"]:
                stats["html"] += 1
            else:
                stats["error"] += 1
        
        if show_progress:
            print()
    
    return valid, invalid, stats


def save_results(valid: list, invalid: list, prefix: str = ""):
    """保存检测结果"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if valid:
        valid_file = f"{prefix}valid_urls_{timestamp}.txt" if prefix else "valid_urls.txt"
        with open(valid_file, "w", encoding="utf-8") as f:
            f.write(f"# 有效的外链列表\n")
            f.write(f"# 检测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 有效数量: {len(valid)}\n\n")
            for line in valid:
                f.write(f"{line}\n")
        print(f"✅ 有效列表已保存到: {valid_file} ({len(valid)} 条)")
    
    if invalid:
        invalid_file = f"{prefix}invalid_urls_{timestamp}.txt" if prefix else "invalid_urls.txt"
        with open(invalid_file, "w", encoding="utf-8") as f:
            f.write(f"# 无效的外链列表\n")
            f.write(f"# 检测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 无效数量: {len(invalid)}\n\n")
            for item in invalid:
                f.write(f"{item['line']}\n")
                f.write(f"  -> 原因：{item['reason']}\n\n")
        print(f"❌ 无效列表已保存到: {invalid_file} ({len(invalid)} 条)")
    
    return valid_file if valid else None, invalid_file if invalid else None


# ==================== 功能1：网易云搜索 ====================
def search_song(song_name: str, limit: int = 100, filter_vip: bool = True) -> list:
    """搜索歌曲，返回格式化的结果列表"""
    url = f"{API_BASE}/search"
    params = {
        "keywords": song_name,
        "limit": limit,
        "type": 1
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data.get('code') == 200:
            songs = data.get('result', {}).get('songs', [])
            results = []
            
            for song in songs:
                privilege = song.get('privilege', {})
                fee = privilege.get('fee', 0)
                st = privilege.get('st', 0)
                pl = privilege.get('pl', 0)
                
                if filter_vip:
                    is_free = (fee == 0) or (pl > 0 and st == 0)
                    if not is_free:
                        continue
                
                singers = ' & '.join([ar['name'] for ar in song.get('artists', [])])
                song_id = song.get('id')
                
                if song_id:
                    mp3_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
                    results.append(f"{singers} - {song.get('name', '')}${mp3_url}")
            
            return results
        else:
            print(f"API错误: {data.get('code')}")
            return []
            
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到API服务！")
        print("请确保已经运行: npx NeteaseCloudMusicApi@latest")
        return []
    except Exception as e:
        print(f"请求失败: {e}")
        return []


def check_api():
    """检查API是否可用"""
    try:
        requests.get(f"{API_BASE}/check", timeout=3)
        return True
    except:
        return False


def function_search():
    """功能1：网易云音乐搜索（带自动检测）"""
    print("\n" + "=" * 60)
    print("功能1：网易云音乐搜索（自动检测）")
    print("=" * 60)
    
    # 检查API
    if not check_api():
        print("\n⚠️ 警告: 本地API服务未启动！")
        print("请另开一个命令行窗口执行: npx NeteaseCloudMusicApi@latest")
        print("\n按任意键返回主菜单...")
        input()
        return
    
    # 是否显示VIP
    show_vip = input("\n是否显示VIP歌曲？(y/n，默认n): ").strip().lower()
    filter_vip = show_vip != 'y'
    
    while True:
        print("\n" + "-" * 60)
        keyword = input("请输入歌名 (直接回车返回主菜单): ").strip()
        
        if not keyword:
            print("返回主菜单...")
            break
        
        print(f"\n正在搜索「{keyword}」...")
        results = search_song(keyword, filter_vip=filter_vip)
        
        if results:
            print(f"\n找到 {len(results)} 首{'免费' if filter_vip else '全部'}歌曲：")
            for idx, r in enumerate(results[:20], 1):
                display = r.replace("https://music.163.com/song/media/outer/url?id=", "🎵 ")
                display = display.replace(".mp3", "")
                print(f"{idx:2d}. {display[:80]}")
            
            if len(results) > 20:
                print(f"... 还有 {len(results) - 20} 首")
            
            # 询问是否检测
            detect = input(f"\n是否检测这 {len(results)} 条链接的有效性？(y/n，默认y): ").strip().lower()
            if detect != 'n':
                print("\n" + "=" * 60)
                print("开始检测...")
                valid, invalid, stats = batch_detect(results, show_progress=True)
                
                # 显示统计
                print("-" * 60)
                print(f"📊 检测完成！")
                print(f"   总计: {stats['total']} 条")
                print(f"   ✅ 有效: {stats['valid']} 条")
                print(f"   ❌ 无效: {stats['invalid']} 条")
                if stats['html'] > 0:
                    print(f"      └─ 伪外链: {stats['html']} 条")
                if stats['error'] > 0:
                    print(f"      └─ 其他错误: {stats['error']} 条")
                
                # 保存结果
                if valid or invalid:
                    valid_file, invalid_file = save_results(valid, invalid, f"{keyword}_")
                    
                    # 询问是否只保存有效链接
                    if valid:
                        save_clean = input(f"\n是否只保存有效链接到单独文件？(y/n): ").strip().lower()
                        if save_clean == 'y':
                            clean_file = f"{keyword}_有效链接.txt"
                            with open(clean_file, "w", encoding="utf-8") as f:
                                for line in valid:
                                    f.write(f"{line}\n")
                            print(f"✅ 已保存到: {clean_file}")
            else:
                # 不检测，直接保存原始搜索结果
                save = input(f"\n是否保存原始搜索结果？(y/n): ").strip().lower()
                if save == 'y':
                    filename = f"{keyword}_歌曲链接.txt"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(f"# 搜索: {keyword}\n")
                        f.write(f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"# 类型: {'仅免费' if filter_vip else '全部'}\n\n")
                        for r in results:
                            f.write(r + "\n")
                    print(f"✅ 已保存到 {filename}")
        else:
            print("未找到免费歌曲，尝试其他关键词或允许显示VIP")


# ==================== 功能2：链接检测 ====================
def function_detect():
    """功能2：外链批量检测"""
    print("\n" + "=" * 60)
    print("功能2：外链批量检测")
    print("=" * 60)
    print("\n说明：")
    print("  - 支持格式：前缀$外链 或 纯外链")
    print("  - ✅ 检测链接是否可访问（HTTP 2xx/3xx）")
    print("  - 🎵 检测Content-Type是否为音频格式（过滤伪外链）")
    print("  - 结果保存到 valid_urls.txt 和 invalid_urls.txt")
    print("\n" + "=" * 60)
    
    print("\n📝 请粘贴内容（多行粘贴，输入空行结束）：")
    print("   格式示例：")
    print("     歌名-歌手$https://example.com/song.mp3")
    print("     或直接：https://example.com/song.mp3")
    print()
    
    lines = []
    while True:
        try:
            line = input()
            if line == "":
                break
            lines.append(line)
        except EOFError:
            break
    
    if not lines:
        print("\n⚠️ 未检测到内容，返回主菜单...")
        input("按回车键继续...")
        return
    
    print(f"\n📋 共 {len(lines)} 条记录待检测")
    
    # 开始检测
    valid, invalid, stats = batch_detect(lines, show_progress=True)
    
    # 保存结果
    print("-" * 60)
    print(f"📊 检测完成！")
    print(f"   总计: {stats['total']} 条")
    print(f"   ✅ 有效音频: {stats['valid']} 条")
    print(f"   ❌ 无效总计: {stats['invalid']} 条")
    
    if valid or invalid:
        save_results(valid, invalid)
    
    print("\n按回车键返回主菜单...")
    input()


# ==================== 功能3：列表转换 ====================
def format_a_to_b(content: str) -> str:
    """格式A转格式B: #EXTINF:-1,XXX\nhttp...mp3 -> XXX$http...mp3"""
    lines = content.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:-1,'):
            title = line.replace('#EXTINF:-1,', '').strip()
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            if j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith('http'):
                    result.append(f"{title}${next_line}")
                    i = j + 1
                else:
                    result.append(line)
                    result.append(next_line)
                    i = j + 1
            else:
                result.append(line)
                i += 1
        else:
            if line and not line.startswith('#EXTM3U'):
                result.append(line)
            i += 1
    return '\n'.join(result)


def format_b_to_a(content: str) -> str:
    """格式B转格式A: XXX$http...mp3 -> #EXTINF:-1,XXX\nhttp...mp3"""
    lines = content.split('\n')
    result = ['#EXTM3U']
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if '$' in line:
            parts = line.split('$', 1)
            if len(parts) == 2 and parts[1].startswith('http'):
                title = parts[0]
                url = parts[1]
                result.append(f"#EXTINF:-1,{title}")
                result.append(url)
            else:
                result.append(line)
        else:
            if line != '#EXTM3U':
                result.append(line)
    
    return '\n'.join(result)


def function_convert():
    """功能3：M3U格式互转"""
    print("\n" + "=" * 60)
    print("功能3：M3U格式互转")
    print("=" * 60)
    print("\n1. 格式A 转 格式B")
    print("   (#EXTINF:-1,歌名 + 链接) -> (歌名$链接)")
    print()
    print("2. 格式B 转 格式A")
    print("   (歌名$链接) -> (#EXTINF:-1,歌名 + 链接)")
    print()
    print("3. 返回主菜单")
    print("=" * 60)
    
    choice = input("\n请选择 (1/2/3): ").strip()
    
    if choice not in ['1', '2']:
        return
    
    file_path = input("请拖入或输入文件路径: ").strip().strip('"')
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        input("按回车键继续...")
        return
    
    # 读取文件
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='gbk') as f:
                content = f.read()
        except Exception as e:
            print(f"❌ 读取文件失败: {e}")
            input("按回车键继续...")
            return
    
    # 转换
    if choice == '1':
        print("正在转换: 格式A -> 格式B")
        result = format_a_to_b(content)
        output_path = file_path.replace('.m3u', '_AtoB.m3u').replace('.txt', '_AtoB.txt')
        if output_path == file_path:
            output_path = file_path + '_converted'
    else:
        print("正在转换: 格式B -> 格式A")
        result = format_b_to_a(content)
        output_path = file_path.replace('.m3u', '_BtoA.m3u').replace('.txt', '_BtoA.txt')
        if output_path == file_path:
            output_path = file_path + '_converted'
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
    
    print(f"\n✅ 转换完成！")
    print(f"输出文件: {output_path}")
    
    # 预览
    lines = result.split('\n')[:10]
    print("\n预览（前10行）:")
    print("-" * 50)
    for line in lines:
        if line:
            print(line[:80] + ('...' if len(line) > 80 else ''))
    print("-" * 50)
    
    input("\n按回车键继续...")


def check_api_status():
    """检查API服务状态"""
    try:
        requests.get(f"{API_BASE}/check", timeout=2)
        return True
    except:
        return False

def start_api_service():
    """启动网易云API服务"""
    import subprocess
    import threading
    import os
    
    # 检查是否已运行
    if check_api_status():
        print("\n✅ API服务已在运行中！")
        return
    
    print("\n正在启动网易云API服务...")
    print("这会在后台打开一个新窗口运行服务")
    print("关闭服务请手动关闭对应的命令行窗口")
    
    try:
        # Windows
        if os.name == 'nt':
            subprocess.Popen(
                "start cmd /k npx NeteaseCloudMusicApi@latest",
                shell=True
            )
        else:
            # Mac/Linux
            subprocess.Popen(
                "npx NeteaseCloudMusicApi@latest",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        
        # 等待服务启动
        print("等待服务启动", end="")
        for i in range(6):
            time.sleep(1)
            print(".", end="", flush=True)
            if check_api_status():
                print("\n✅ API服务启动成功！")
                return
        
        print("\n⚠️ 请手动确认服务是否启动")
        print("可以访问 http://localhost:3000 测试")
        
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        print("请手动在命令行运行: npx NeteaseCloudMusicApi@latest")


def main():
    while True:
        print("\n" + "=" * 60)
        print("         🎵 音乐工具箱 🎵")
        print("=" * 60)
        print()
        
        # 显示API服务状态
        if check_api_status():
            print("   🌐 API服务: ✅ 已启动")
        else:
            print("   🌐 API服务: ❌ 未启动")
        print()
        
        print("   0. 🚀 启动API服务（功能1依赖）")
        print("   1. 🔍 网易云搜索（自动检测）")
        print("   2. 🔗 外链批量检测")
        print("   3. 📑 M3U格式互转")
        print("   4. 🚪 退出")
        print()
        print("=" * 60)
        
        choice = input("\n请选择功能 (0/1/2/3/4): ").strip()
        
        if choice == '0':
            start_api_service()
            input("\n按回车键继续...")
        elif choice == '1':
            if not check_api_status():
                print("\n❌ API服务未启动！")
                start = input("是否立即启动？(y/n): ").strip().lower()
                if start == 'y':
                    start_api_service()
                    if check_api_status():
                        function_search()
                    else:
                        input("按回车键继续...")
                else:
                    continue
            else:
                function_search()
        elif choice == '2':
            function_detect()
        elif choice == '3':
            function_convert()
        elif choice == '4':
            print("\n👋 再见！")
            sys.exit(0)
        else:
            print("\n❌ 无效选择，请重新输入")
            input("按回车键继续...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 已取消，再见！")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        input("按回车键退出...")
        sys.exit(1)