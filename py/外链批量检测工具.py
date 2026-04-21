#!/usr/bin/env python3
"""
外链批量检测工具
- 支持格式：前缀$外链 或 纯外链
- 只检测链接是否有效
- 输出：有效列表保持原格式，无效列表单独保存
"""

import requests


def parse_line(line: str) -> tuple:
    """
    解析一行文本，返回 (前缀, 外链)
    格式1：歌名-歌手$外链
    格式2：纯外链
    返回：(前缀部分, 外链URL)
    """
    line = line.strip()
    if not line:
        return None, None
    
    # 按 $ 分割
    if '$' in line:
        parts = line.split('$', 1)
        prefix = parts[0]
        url = parts[1].strip()
        return prefix, url
    else:
        return None, line


def check_url_validity(url: str) -> dict:
    """
    检测链接是否有效
    返回: {"valid": bool, "message": str}
    """
    if not url.startswith(('http://', 'https://')):
        return {"valid": False, "message": "格式错误：不是有效的HTTP链接"}
    
    try:
        try:
            response = requests.head(url, timeout=10, allow_redirects=True)
        except:
            response = requests.get(url, timeout=10, stream=True, allow_redirects=True)
            response.close()
        
        if response.status_code in [200, 302, 301, 307, 308]:
            return {"valid": True, "message": "有效"}
        elif response.status_code == 404:
            return {"valid": False, "message": "404 链接失效"}
        elif response.status_code == 403:
            return {"valid": False, "message": "403 禁止访问"}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        return {"valid": False, "message": "超时"}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "message": "连接失败"}
    except requests.exceptions.RequestException as e:
        return {"valid": False, "message": f"请求失败: {str(e)[:50]}"}


def main():
    print("=" * 60)
    print("外链批量检测工具")
    print("=" * 60)
    print("\n说明：")
    print("  - 支持格式：前缀$外链 或 纯外链")
    print("  - 检测链接是否可访问（HTTP 2xx/3xx 视为有效）")
    print("  - 结果保存到 valid_urls.txt 和 invalid_urls.txt")
    print("=" * 60)
    
    print("\n📝 请粘贴内容（多行粘贴，输入空行结束）：")
    print("   格式示例：")
    print("     歌名-歌手$https://example.com/song.mp3")
    print("     或直接：https://example.com/song.mp3")
    print()
    
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    
    if not lines:
        print("\n⚠️ 未检测到内容，退出")
        return
    
    print(f"\n📋 共 {len(lines)} 条记录待检测")
    print("\n🔍 开始检测...\n")
    
    valid = []
    invalid = []
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
            
        prefix, url = parse_line(line)
        
        # 显示当前检测
        if prefix:
            display = prefix[:40] + "..." if len(prefix) > 40 else prefix
        else:
            display = url[:50] + "..." if url and len(url) > 50 else url
        print(f"[{i}/{len(lines)}] {display}")
        
        if not url:
            print(f"   ⚠️ 格式错误：没有找到链接\n")
            invalid.append({
                "line": line,
                "reason": "格式错误：没有找到链接"
            })
            continue
        
        result = check_url_validity(url)
        
        if result["valid"]:
            print(f"   ✅ {result['message']}")
            valid.append(line)
        else:
            print(f"   ❌ {result['message']}")
            invalid.append({
                "line": line,
                "reason": result["message"]
            })
        print()
    
    # 保存结果
    if valid:
        with open("valid_urls.txt", "w", encoding="utf-8") as f:
            f.write("# 有效的外链列表\n\n")
            for line in valid:
                f.write(f"{line}\n")
        print(f"✅ 有效列表已保存到: valid_urls.txt ({len(valid)} 条)")
    else:
        print("⚠️ 没有检测到有效链接")
    
    if invalid:
        with open("invalid_urls.txt", "w", encoding="utf-8") as f:
            f.write("# 无效的外链列表\n\n")
            for item in invalid:
                f.write(f"{item['line']}\n")
                f.write(f"  -> 原因：{item['reason']}\n\n")
        print(f"❌ 无效列表已保存到: invalid_urls.txt ({len(invalid)} 条)")
    else:
        print("🎉 所有链接均有效！")
    
    print("\n" + "-" * 60)


if __name__ == "__main__":
    main()