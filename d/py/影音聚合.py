#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超级影音工具箱 - 手机版
音乐播放器(随机循环) + 影视搜索(单/聚合) + 工具
"""

import os
import re
import requests
import json
import time
import subprocess
import random
import socket
import threading
import webbrowser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template_string, send_file

# ==================== 路径配置 ====================
import platform

# 根据系统自动选择音乐目录
if platform.system() == "Windows":
    MUSIC_BASE = "./downloaded_music"  # Windows 电脑
    M3U_PATH = f"{MUSIC_BASE}/list/mp3list.m3u"
else:
    MUSIC_BASE = "/storage/emulated/0/0-pcrock/mp3"  # Android 手机
    M3U_PATH = f"{MUSIC_BASE}/list/mp3list.m3u"

ONLINE_M3U_URL = "https://pcrock99.github.io/d1/d/list/mp3list.m3u"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

# 根据系统自动选择导出目录
if platform.system() == "Windows":
    EXPORT_DIR = "./exported_music"
else:
    EXPORT_DIR = "/storage/emulated/0/0-pcrock/py"

# 根据系统自动选择收藏文件路径
if platform.system() == "Windows":
    FAVORITES_FILE = "./favorites.json"  # Windows 电脑
else:
    FAVORITES_FILE = "/storage/emulated/0/0-pcrock/py/favorites.json"  # Android 手机

# 网易云API配置
API_BASE = "http://localhost:3000"
DETECT_TIMEOUT = 10

# 影视配置
REQUEST_TIMEOUT = 15
MAX_CONCURRENT = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
PAGE_SIZE = 50
HEALTH_FILE = "api_health.json"

# ==================== 加载影视接口配置 ====================
def load_api_config():
    import requests
    # 在线配置地址
    online_config_url = "https://pcrock99.github.io/d1/d/jk/config.json"
    
    # 1. 尝试从在线地址获取
    try:
        print(f"正在从在线地址加载配置: {online_config_url}")
        resp = requests.get(online_config_url, timeout=10)
        if resp.status_code == 200:
            config = resp.json()
            if config.get("api_list"):
                print("✅ 在线配置加载成功")
                return config["api_list"]
            else:
                print("⚠️ 在线配置中无 api_list 字段")
        else:
            print(f"⚠️ 在线配置获取失败，HTTP状态码: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ 在线配置加载异常: {e}")
    
    # 2. 回退到本地 config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if config.get("api_list"):
                    print("✅ 本地配置加载成功")
                    return config["api_list"]
        except Exception as e:
            print(f"本地配置加载失败: {e}")
    
    # 3. 最终回退到默认配置
    print("⚠️ 使用默认配置")
    return [
        {"name": "卧龙资源", "url": "https://collect.wolongzyw.com/api.php/provide/vod/at/xml/", "format": "json", "searchable": True, "enabled": True, "group": "主站"},
        # 可以在这里放几个最稳定的默认接口
    ]

API_LIST = load_api_config()

# ==================== 初始化目录 ====================
def init_dirs():
    os.makedirs(f"{MUSIC_BASE}/list", exist_ok=True)
    os.makedirs(MUSIC_BASE, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
init_dirs()

# ==================== 通用函数 ====================
def check_url_validity(url: str, timeout: int = DETECT_TIMEOUT) -> dict:
    if not url.startswith(('http://', 'https://')):
        return {"valid": False, "message": "格式错误"}
    try:
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 405:
                raise Exception("HEAD不支持")
        except:
            response = requests.get(url, timeout=timeout, stream=True, allow_redirects=True)
            response.close()
        if response.status_code not in [200, 302, 301, 307, 308]:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
        content_type = response.headers.get('Content-Type', '').lower()
        audio_types = ['audio/mpeg', 'audio/mp4', 'audio/x-m4a', 'audio/flac', 'audio/wav', 'audio/ogg', 'audio/aac']
        if 'text/html' in content_type:
            return {"valid": False, "message": "返回HTML页面"}
        if any(t in content_type for t in audio_types):
            return {"valid": True, "message": "有效音频"}
        return {"valid": False, "message": "非音频格式"}
    except:
        return {"valid": False, "message": "请求失败"}

# ==================== 网易云音乐功能 ====================
def check_api_status():
    try:
        requests.get(f"{API_BASE}/check", timeout=2)
        return True
    except:
        return False

def start_api_service():
    if check_api_status():
        return "已在运行"
    try:
        subprocess.Popen("npx NeteaseCloudMusicApi@latest", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        return "已启动" if check_api_status() else "启动中"
    except:
        return "启动失败"

def search_song(song_name: str, limit: int = 100, filter_vip: bool = True) -> list:
    if not check_api_status():
        return []
    try:
        resp = requests.get(f"{API_BASE}/search", params={"keywords": song_name, "limit": limit, "type": 1}, timeout=10)
        data = resp.json()
        if data.get('code') == 200:
            songs = data.get('result', {}).get('songs', [])
            results = []
            for song in songs:
                privilege = song.get('privilege', {})
                fee = privilege.get('fee', 0)
                if filter_vip and fee != 0:
                    continue
                singers = ' & '.join([ar['name'] for ar in song.get('artists', [])])
                song_id = song.get('id')
                if song_id:
                    mp3_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
                    results.append({"name": f"{singers} - {song.get('name', '')}", "url": mp3_url, "id": song_id})
            return results
        return []
    except:
        return []

def download_song(title, url):
    safe_name = "".join(c for c in title if c not in r'\/:*?"<>|')
    save_path = os.path.join(MUSIC_BASE, f"{safe_name}.mp3")
    if os.path.exists(save_path):
        return "已存在"
    try:
        with requests.get(url, stream=True, timeout=30) as res:
            res.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in res.iter_content(8192):
                    f.write(chunk)
        return "✅ 已保存"
    except Exception as e:
        return "下载失败"

def get_local_mp3_list():
    if not os.path.exists(MUSIC_BASE):
        return []
    songs = []
    for f in os.listdir(MUSIC_BASE):
        if f.lower().endswith('.mp3'):
            songs.append({
                "name": f.replace('.mp3', ''),
                "url": f"/api/local/music/{f}"
            })
    return songs

def get_online_playlist():
    # 确保目录存在
    os.makedirs(os.path.dirname(M3U_PATH), exist_ok=True)
    
    print(f"[DEBUG] M3U_PATH: {M3U_PATH}")
    print(f"[DEBUG] 文件是否存在: {os.path.exists(M3U_PATH)}")
    
    if not os.path.exists(M3U_PATH):
        try:
            print(f"[DEBUG] 开始下载: {ONLINE_M3U_URL}")
            r = requests.get(ONLINE_M3U_URL, timeout=10)
            print(f"[DEBUG] 下载状态码: {r.status_code}")
            if r.status_code == 200:
                with open(M3U_PATH, "wb") as f:
                    f.write(r.content)
                print(f"[DEBUG] 歌单已保存到: {M3U_PATH}")
            else:
                print(f"[DEBUG] 下载失败")
                return []
        except Exception as e:
            print(f"[DEBUG] 下载异常: {e}")
            return []
    
    songs = []
    title = None
    try:
        with open(M3U_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    title = line.split(",", 1)[-1].strip()
                elif line and not line.startswith("#") and title:
                    songs.append({"name": title, "url": line})
                    title = None
        print(f"[DEBUG] 解析到 {len(songs)} 首歌曲")
    except Exception as e:
        print(f"[DEBUG] 解析异常: {e}")
    
    return songs

# ==================== 影视功能 ====================
def build_api_url(api_config):
    url = api_config["url"]
    if not url.endswith('/'):
        url = url + '/'
    fmt = api_config.get("format", "json")
    if fmt == 'xml':
        if not url.endswith('xml/'):
            url = url + 'at/xml/'
    else:
        if not url.endswith('json/'):
            url = url + 'at/json/'
    return url

def extract_episodes(text):
    episodes = []
    if not text or '.m3u8' not in text:
        return episodes
    if '#' in text:
        items = text.split('#')
    else:
        items = [text]
    for item in items:
        if not item.strip():
            continue
        if '$' in item:
            parts = item.split('$')
            if len(parts) >= 2:
                ep_name = parts[0].strip()
                ep_url = None
                for part in reversed(parts):
                    if '.m3u8' in part:
                        ep_url = part.split('#')[0].strip()
                        break
                if ep_url and ep_url.startswith('http'):
                    episodes.append({"name": ep_name, "url": ep_url})
        elif '.m3u8' in item and item.startswith('http'):
            episodes.append({"name": "正片", "url": item.split('#')[0].strip()})
    return episodes

def parse_json_videos(json_text, source_name):
    videos = []
    try:
        data = json.loads(json_text)
        video_list = data.get('list', data.get('data', data.get('videos', [])))
        if not video_list and isinstance(data, list):
            video_list = data
        for item in video_list:
            name = item.get('vod_name', item.get('name', item.get('title', '')))
            if not name:
                continue
            play_url = item.get('vod_play_url', item.get('play_url', item.get('url', '')))
            episodes = extract_episodes(play_url) if play_url else []
            if name and episodes:
                videos.append({"name": name, "episodes": episodes, "source": source_name})
    except:
        pass
    return videos

def parse_xml_videos(xml_text, source_name):
    import xml.etree.ElementTree as ET
    videos = []
    try:
        root = ET.fromstring(xml_text)
        for video_node in root.findall('.//video'):
            name_elem = video_node.find('name')
            if name_elem is None or not name_elem.text:
                continue
            name = name_elem.text.strip()
            episodes = []
            for dd in video_node.findall('.//dd'):
                if dd.text and '.m3u8' in dd.text:
                    episodes = extract_episodes(dd.text)
                    if episodes:
                        break
            if name and episodes:
                videos.append({"name": name, "episodes": episodes, "source": source_name})
    except:
        pass
    return videos

def search_single_api(api_config, keyword, category_id=None, page=1):
    if not api_config.get("enabled", True):
        return [], 1
    source_name = api_config["name"]
    url = build_api_url(api_config)
    fmt = api_config.get("format", "json")
    try:
        if api_config.get("searchable", True) and keyword:
            params = {"ac": "videolist", "wd": keyword, "pg": page, "pagesize": PAGE_SIZE}
        else:
            params = {"ac": "videolist", "pg": page, "pagesize": PAGE_SIZE}
        if category_id:
            params["t"] = category_id
        print(f"[DEBUG] 请求: {url}, params={params}")
        resp = requests.get(url, params=params, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.encoding = 'utf-8'
        
        if fmt == 'xml':
            parsed = parse_xml_videos(resp.text, source_name)
        else:
            parsed = parse_json_videos(resp.text, source_name)
        
        total_pages = 1
        try:
            if fmt == 'xml':
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                list_node = root.find('list')
                if list_node is not None and list_node.get('pagecount'):
                    total_pages = int(list_node.get('pagecount'))
            else:
                data = json.loads(resp.text)
                total_pages = data.get('pagecount', data.get('total_pages', 1))
        except:
            pass
        
        if not api_config.get("searchable", True) and keyword:
            parsed = [v for v in parsed if keyword.lower() in v['name'].lower()]
        return parsed, total_pages
    except Exception as e:
        print(f"搜索失败 {source_name}: {e}")
        return [], 1

def fetch_categories(api_config):
    url = build_api_url(api_config)
    params = {"ac": "list"}
    fmt = api_config.get("format", "json")
    try:
        print(f"[DEBUG] 获取分类: {url}, params={params}")
        resp = requests.get(url, params=params, headers={'User-Agent': USER_AGENT}, timeout=10)
        resp.encoding = 'utf-8'
        categories = []
        
        if fmt == 'xml':
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            for class_node in root.findall('.//class'):
                type_id = class_node.find('type_id')
                type_name = class_node.find('type_name')
                if type_id is not None and type_name is not None and type_id.text and type_name.text:
                    categories.append({"id": type_id.text, "name": type_name.text})
        else:
            data = json.loads(resp.text)
            class_list = data.get('class', data.get('list', []))
            for item in class_list:
                cid = item.get('type_id', item.get('id', ''))
                cname = item.get('type_name', item.get('name', ''))
                if cid and cname:
                    categories.append({"id": cid, "name": cname})
        print(f"[DEBUG] 获取到 {len(categories)} 个分类")
        return categories
    except Exception as e:
        print(f"获取分类失败: {e}")
        return []

# ==================== M3U转换 ====================
def convert_a_to_b(content: str) -> str:
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
                    i += 1
            else:
                result.append(line)
                i += 1
        else:
            if line and not line.startswith('#EXTM3U'):
                result.append(line)
            i += 1
    return '\n'.join(result)

def convert_b_to_a(content: str) -> str:
    lines = content.split('\n')
    result = ['#EXTM3U']
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if '$' in line:
            parts = line.split('$', 1)
            if len(parts) == 2 and parts[1].startswith('http'):
                result.append(f"#EXTINF:-1,{parts[0]}")
                result.append(parts[1])
            else:
                result.append(line)
        elif line != '#EXTM3U':
            result.append(line)
    return '\n'.join(result)

# ==================== Flask 应用 ====================
app = Flask(__name__)

# 主页面模板
MAIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>🎵 pcrock影音聚合</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; }
        .container { max-width: 700px; margin: 0 auto; padding: 16px; }
        .header { text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 20px; margin-bottom: 20px; color: white; }
        .header h1 { font-size: 1.6em; }
        .tabs { display: flex; gap: 6px; margin-bottom: 20px; flex-wrap: wrap; justify-content: center; }
        .tab-btn { padding: 10px 18px; border: none; border-radius: 30px; font-size: 13px; font-weight: bold; cursor: pointer; background: rgba(255,255,255,0.1); color: white; transition: all 0.3s; }
        .tab-btn.active { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .tab-content { display: none; background: rgba(255,255,255,0.05); border-radius: 20px; padding: 16px; backdrop-filter: blur(10px); }
        .tab-content.active { display: block; }
        .status-bar { background: rgba(0,0,0,0.3); padding: 8px 12px; border-radius: 10px; margin-top: 12px; font-size: 11px; color: #aaa; text-align: center; }
        button { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; padding: 8px 16px; border-radius: 8px; color: white; cursor: pointer; font-weight: bold; font-size: 13px; }
        button:active { transform: scale(0.98); }
        input, select, textarea { background: #0f3460; border: 1px solid #1a4a7a; padding: 8px 12px; border-radius: 8px; color: white; font-size: 13px; }
        input:focus, select:focus { outline: none; border-color: #667eea; }
        .search-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
        .search-bar input { flex: 2; min-width: 120px; }
        
        /* 自定义播放器样式 */
        .player-card { background: linear-gradient(135deg, #667eea20 0%, #764ba220 100%); border-radius: 20px; padding: 20px; margin-bottom: 20px; text-align: center; }
        .current-song { font-size: 18px; font-weight: bold; margin: 10px 0; word-break: break-word; min-height: 60px; }
        .mode-select { display: flex; gap: 10px; justify-content: center; margin-bottom: 15px; }
        .mode-btn { padding: 6px 16px; background: rgba(255,255,255,0.1); border-radius: 20px; font-size: 12px; cursor: pointer; }
        .mode-btn.active { background: #667eea; }
        
        /* 自定义控制栏 */
        .custom-controls { margin-top: 15px; }
        .progress-bar { width: 100%; height: 4px; background: rgba(255,255,255,0.2); border-radius: 2px; cursor: pointer; margin: 15px 0; }
        .progress-fill { width: 0%; height: 100%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 2px; }
        .time-info { display: flex; justify-content: space-between; font-size: 11px; color: #aaa; margin-bottom: 10px; }
        .control-buttons { display: flex; justify-content: center; align-items: center; gap: 30px; margin: 20px 0; }
        .ctrl-btn { width: 55px; height: 55px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; color: white; font-size: 22px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; }
        .ctrl-btn:active { transform: scale(0.95); }
        .ctrl-btn-small { width: 45px; height: 45px; font-size: 18px; background: rgba(255,255,255,0.1); }
        .play-pause-btn { width: 65px; height: 65px; font-size: 28px; }
        
        /* 列表样式 */
        .list-item { background: rgba(255,255,255,0.05); padding: 10px 12px; border-radius: 10px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; cursor: pointer; }
        .list-item:hover { background: rgba(102,126,234,0.2); }
        .item-name { flex: 2; font-size: 13px; }
        .item-meta { color: #667eea; font-size: 11px; margin-left: 10px; }
        .play-icon { color: #4caf50; font-size: 14px; margin-left: 8px; }
        .btn-sm { padding: 4px 10px; font-size: 11px; }
        .episode-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; max-height: 200px; overflow-y: auto; }
        .episode-btn { padding: 6px 12px; background: #0f3460; border-radius: 20px; cursor: pointer; font-size: 11px; }
        .episode-btn:active { background: #667eea; }
        textarea { width: 100%; min-height: 100px; font-family: monospace; font-size: 11px; margin: 8px 0; }
        .flex-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
        hr { border-color: rgba(255,255,255,0.1); margin: 15px 0; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🎵 pcrock影音聚合</h1>
    </div>
    
    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('player')">🎵 音乐播放</button>
        <button class="tab-btn" onclick="switchTab('search')">🔍 音乐搜索</button>
        <button class="tab-btn" onclick="switchTab('video')">🎬 影视搜索</button>
        <button class="tab-btn" onclick="switchTab('tools')">🔧 工具</button>
        <button class="tab-btn" onclick="switchTab('favorites')">⭐ 我的收藏</button>
    </div>
    
    <!-- ==================== 音乐播放器 ==================== -->
    <div id="playerTab" class="tab-content active">
        <div class="mode-select">
            <div class="mode-btn" data-mode="local" onclick="setPlayMode('local')">📱 本地</div>
            <div class="mode-btn" data-mode="online" onclick="setPlayMode('online')">🌍 在线歌单</div>
        </div>
        
        <div class="player-card">
            <div style="color:#aaa; font-size:12px;">正在播放</div>
            <div class="current-song" id="currentSongName">-</div>
            
            <audio id="audioPlayer" style="display:none;"></audio>
            
            <div class="custom-controls">
                <div class="time-info">
                    <span id="currentTime">0:00</span>
                    <span id="duration">0:00</span>
                </div>
                <div class="progress-bar" id="progressBar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <div class="control-buttons">
                    <button class="ctrl-btn ctrl-btn-small" onclick="prevSong()">⏮</button>
                    <button class="ctrl-btn play-pause-btn" id="playPauseBtn" onclick="togglePlayPause()">▶</button>
                    <button class="ctrl-btn ctrl-btn-small" onclick="nextSong()">⏭</button>
                    <button class="ctrl-btn ctrl-btn-small" onclick="downloadCurrentSong()">💾</button>
                </div>
            </div>
        </div>
        <div id="playerStatus" class="status-bar">就绪</div>
    </div>
    
    <!-- ==================== 音乐搜索 ==================== -->
    <div id="searchTab" class="tab-content">
        <div class="search-bar">
            <input type="text" id="searchKeyword" placeholder="输入歌名..." onkeypress="if(event.keyCode==13) doSearch()">
            <label style="display:flex; align-items:center; gap:4px; font-size:12px;"><input type="checkbox" id="filterVip" checked> 过滤VIP</label>
            <button onclick="doSearch()">🔍 搜索</button>
            <button onclick="checkApi()">📡 API状态</button>
            <button onclick="startApi()">🚀 启动API</button>
        </div>
        <div id="searchStatus" class="status-bar">API: 检测中...</div>
        <div id="searchResults"></div>
        <button onclick="exportValidLinks()" style="margin-top:10px; width:100%;">📁 导出有效链接</button>
    </div>
    
    <!-- ==================== 影视搜索 ==================== -->
    <div id="videoTab" class="tab-content">
        <div class="search-bar">
            <input type="text" id="videoKeyword" placeholder="影视名称..." onkeypress="if(event.keyCode==13) searchVideo()">
            <select id="searchMode" onchange="toggleVideoMode()">
                <option value="all">🌐 聚合搜索</option>
                <option value="single">📡 单接口</option>
            </select>
            <button onclick="searchVideo()">🔍 搜索</button>
        </div>
        <div id="singleApiPanel" style="display:none;">
            <div class="search-bar" style="margin-top:8px;">
                <select id="apiSelect" style="flex:1" onchange="loadCategories()"></select>
                <select id="categorySelect" style="flex:1">
                    <option value="">📁 全部</option>
                </select>
                <button onclick="browseCategory()">📂 浏览</button>
            </div>
        </div>
        <div id="videoStatus" class="status-bar">就绪</div>
        <div id="videoResults"></div>
        <div id="episodePanel" style="display:none; margin-top:15px; background:rgba(0,0,0,0.3); border-radius:12px; padding:12px;">
            <div><strong id="currentVideoName"></strong> <span id="episodeCount"></span></div>
            <div class="episode-list" id="episodeList"></div>
        </div>
        <div id="videoPagination" style="display:flex; justify-content:center; gap:10px; margin-top:12px;"></div>
    </div>

<!-- ==================== 我的收藏 ==================== -->
<div id="favoritesTab" class="tab-content">
    <div class="search-bar">
        <button onclick="loadFavorites()">🔄 刷新</button>
        <button onclick="clearAllFavorites()" style="background:#e94560;">🗑️ 清空全部</button>
    </div>
    <div id="favoritesStatus" class="status-bar">就绪</div>
    <div id="favoritesResults"></div>
</div>
    
    <!-- ==================== 工具 ==================== -->
    <div id="toolsTab" class="tab-content">
        <h3>🔗 外链检测</h3>
        <textarea id="detectUrls" placeholder="歌名$链接 或 纯链接，每行一条"></textarea>
        <button onclick="detectLinks()">检测</button>
        <div id="detectResult"></div>
        <hr>
        <h3>📑 M3U转换</h3>
        <div class="flex-row">
            <button onclick="convertM3U('toTxt')">M3U → TXT</button>
            <button onclick="convertM3U('toM3u')">TXT → M3U</button>
        </div>
        <textarea id="convertContent" placeholder="粘贴内容..."></textarea>
        <div id="convertResult"></div>
    </div>
    
    <div id="globalStatus" class="status-bar">✅ 就绪</div>
</div>

<script>
    // ==================== 全局变量 ====================
    let currentPlaylist = [];
    let currentPlayIndex = 0;
    let playMode = 'local';
    let audioPlayer = null;
    let isPlaying = false;
    let searchResults = [];
    let videoList = [];
    let currentEpisodes = [];
    let currentVideoName = "";
    let videoTotalPages = 1;
    let videoCurrentPage = 1;
    let currentApi = "";
    let currentCategory = "";
    
    // 初始化
    document.addEventListener('DOMContentLoaded', () => {
        audioPlayer = document.getElementById('audioPlayer');
        
        // 事件监听
        audioPlayer.addEventListener('timeupdate', updateProgress);
        audioPlayer.addEventListener('loadedmetadata', updateDuration);
        audioPlayer.addEventListener('ended', () => nextSong());
        audioPlayer.addEventListener('play', () => {
            isPlaying = true;
            document.getElementById('playPauseBtn').innerHTML = '⏸';
        });
        audioPlayer.addEventListener('pause', () => {
            isPlaying = false;
            document.getElementById('playPauseBtn').innerHTML = '▶';
        });
        
        // 进度条点击
        document.getElementById('progressBar').addEventListener('click', seek);
        
        // setPlayMode('online'); // 改成 online，默认播放在线歌单
        checkApi();
        loadApis();
    });

    function downloadCurrentSong() {
        if (currentPlaylist.length === 0) {
            updateStatus('没有歌曲可下载');
            return;
        }
        const song = currentPlaylist[currentPlayIndex];
        if (!song || !song.url) {
            updateStatus('当前歌曲无效');
            return;
        }
        updateStatus(`下载中: ${song.name}`);
        fetch('/api/music/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: song.name, url: song.url })
        }).then(r => r.json()).then(data => {
            updateStatus(data.message);
            // 如果是本地模式，刷新本地列表
            if (playMode === 'local') {
                loadLocalSongs();
            }
        }).catch(e => updateStatus('下载失败: ' + e.message));
    }

    function switchTab(tab) {
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(tab + 'Tab').classList.add('active');
        event.target.classList.add('active');
        if (tab === 'search') checkApi();
        if (tab === 'video') loadApis();
    }
    
    // ==================== 音乐播放器（随机循环） ====================
    function setPlayMode(mode) {
        playMode = mode;
        document.querySelectorAll('.mode-btn').forEach(btn => {
            if (btn.dataset.mode === mode) btn.classList.add('active');
            else btn.classList.remove('active');
        });
        if (mode === 'local') loadLocalSongs();
        else loadOnlineSongs();
    }
    
    function loadLocalSongs() {
        fetch('/api/local/songs').then(r => r.json()).then(data => {
            if (data.songs.length > 0) {
                currentPlaylist = data.songs;
                currentPlayIndex = Math.floor(Math.random() * currentPlaylist.length);
                playCurrent();
                updateStatus(`本地 ${currentPlaylist.length} 首，随机循环`);
            } else {
                updateStatus(`本地无歌曲，请先下载`);
                document.getElementById('currentSongName').innerText = '无歌曲';
            }
        });
    }
    
    function loadOnlineSongs() {
        fetch('/api/playlist/load').then(r => r.json()).then(data => {
            if (data.songs.length > 0) {
                currentPlaylist = data.songs;
                currentPlayIndex = Math.floor(Math.random() * currentPlaylist.length);
                playCurrent();
                updateStatus(`歌单 ${currentPlaylist.length} 首，随机循环`);
            } else {
                updateStatus(`歌单加载失败`);
                document.getElementById('currentSongName').innerText = '加载失败';
            }
        });
    }
    
    function playCurrent() {
        if (currentPlaylist.length === 0) return;
        const song = currentPlaylist[currentPlayIndex];
        document.getElementById('currentSongName').innerText = song.name;
        audioPlayer.src = song.url;
        audioPlayer.play();
        updateStatus(`播放: ${song.name}`);
    }
    
    function togglePlayPause() {
        if (audioPlayer.paused) {
            audioPlayer.play();
        } else {
            audioPlayer.pause();
        }
    }
    
    function prevSong() {
        if (currentPlaylist.length === 0) return;
        // 上一首：随机跳转（随机循环风格）
        let prevIndex = Math.floor(Math.random() * currentPlaylist.length);
        if (currentPlaylist.length > 1 && prevIndex === currentPlayIndex) {
            prevIndex = (prevIndex + 1) % currentPlaylist.length;
        }
        currentPlayIndex = prevIndex;
        playCurrent();
    }
    
    function nextSong() {
        if (currentPlaylist.length === 0) return;
        // 随机下一首
        let nextIndex = Math.floor(Math.random() * currentPlaylist.length);
        if (currentPlaylist.length > 1 && nextIndex === currentPlayIndex) {
            nextIndex = (nextIndex + 1) % currentPlaylist.length;
        }
        currentPlayIndex = nextIndex;
        playCurrent();
    }
    
    function updateProgress() {
        if (audioPlayer.duration) {
            const percent = (audioPlayer.currentTime / audioPlayer.duration) * 100;
            document.getElementById('progressFill').style.width = percent + '%';
            document.getElementById('currentTime').innerText = formatTime(audioPlayer.currentTime);
        }
    }
    
    function updateDuration() {
        document.getElementById('duration').innerText = formatTime(audioPlayer.duration);
    }
    
    function formatTime(seconds) {
        if (isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return mins + ':' + (secs < 10 ? '0' + secs : secs);
    }
    
    function seek(e) {
        const bar = e.currentTarget;
        const rect = bar.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        audioPlayer.currentTime = x * audioPlayer.duration;
    }
    
    // ==================== 音乐搜索 ====================
    function checkApi() {
        fetch('/api/music/status').then(r => r.json()).then(data => {
            document.getElementById('searchStatus').innerHTML = `API: ${data.status}`;
        });
    }
    
    function startApi() {
        document.getElementById('searchStatus').innerHTML = '正在启动...';
        fetch('/api/music/start').then(r => r.json()).then(data => {
            document.getElementById('searchStatus').innerHTML = `API: ${data.message}`;
            setTimeout(checkApi, 3000);
        });
    }
    
    function doSearch() {
        const keyword = document.getElementById('searchKeyword').value.trim();
        const filterVip = document.getElementById('filterVip').checked;
        if (!keyword) { updateStatus('请输入歌名'); return; }
        updateStatus('搜索中...');
        fetch('/api/music/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, filter_vip: filterVip })
        }).then(r => r.json()).then(data => {
            // 过滤掉无效链接
            const allResults = data.results;
            updateStatus(`检测有效性中...`);
            
            // 批量检测有效性
            Promise.all(allResults.map(song => 
                fetch('/api/tools/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: song.url })
                }).then(r => r.json()).then(result => ({ song, valid: result.valid }))
            )).then(results => {
                searchResults = results.filter(r => r.valid).map(r => r.song);
                renderSearchResults();
                updateStatus(`找到 ${searchResults.length} 首有效歌曲 (共检测 ${allResults.length} 首)`);
            });
        });
    }
    
    function renderSearchResults() {
        const container = document.getElementById('searchResults');
        if (searchResults.length === 0) {
            container.innerHTML = '<div class="status-bar">暂无结果，请先启动API</div>';
            return;
        }
        container.innerHTML = searchResults.map((song, idx) => `
            <div class="list-item" onclick="playSearchSong(${idx})">
                <div class="item-name">🎵 ${song.name}</div>
                <div>
                    <button class="btn-sm" onclick="event.stopPropagation(); downloadSearchSong(${idx})">💾 下载</button>
                </div>
            </div>
        `).join('');
    }
    
    function playSearchSong(idx) {
        const song = searchResults[idx];
        currentPlaylist = [song];
        currentPlayIndex = 0;
        playCurrent();
        updateStatus(`播放: ${song.name}`);
        document.querySelectorAll('.tab-btn')[0].click();
    }
    
    function downloadSearchSong(idx) {
        const song = searchResults[idx];
        updateStatus(`下载中: ${song.name}`);
        fetch('/api/music/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: song.name, url: song.url })
        }).then(r => r.json()).then(data => {
            updateStatus(data.message);
        });
    }
    
    function exportValidLinks() {
        if (searchResults.length === 0) {
            updateStatus('没有有效歌曲可导出');
            return;
        }
        updateStatus('导出中...');
        fetch('/api/tools/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ songs: searchResults })
        }).then(r => r.json()).then(data => {
            updateStatus(`✅ 导出完成: ${data.file}，共 ${data.valid_count} 首`);
        }).catch(e => updateStatus('导出失败: ' + e.message));
    }
    
    // ==================== 影视搜索 ====================
    function toggleVideoMode() {
        const mode = document.getElementById('searchMode').value;
        document.getElementById('singleApiPanel').style.display = mode === 'single' ? 'block' : 'none';
        if (mode === 'single') {
            loadApis();
        }
    }
    
    function loadApis() {
        fetch('/api/apis').then(r => r.json()).then(data => {
            const select = document.getElementById('apiSelect');
            select.innerHTML = '<option value="">请选择接口</option>' + data.map(api => `<option value="${api.name}">${api.name} (${api.group})</option>`).join('');
        });
    }
    
    function loadCategories() {
        const api = document.getElementById('apiSelect').value;
        if (!api) {
            document.getElementById('categorySelect').innerHTML = '<option value="">📁 全部</option>';
            return;
        }
        updateStatus('加载分类中...');
        fetch(`/api/categories?api=${encodeURIComponent(api)}`)
            .then(r => r.json())
            .then(data => {
                const select = document.getElementById('categorySelect');
                if (data && data.length > 0) {
                    select.innerHTML = '<option value="">📁 全部</option>' + data.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
                    updateStatus(`加载 ${data.length} 个分类`);
                } else {
                    select.innerHTML = '<option value="">📁 无分类</option>';
                    updateStatus('该接口无分类数据');
                }
            })
            .catch(e => {
                console.error(e);
                updateStatus('加载分类失败');
            });
    }
    
    function searchVideo() {
        const keyword = document.getElementById('videoKeyword').value.trim();
        const mode = document.getElementById('searchMode').value;
        if (!keyword && mode !== 'single') { updateStatus('请输入影视名称'); return; }
        updateStatus('搜索中...');
        
        let body = { keyword, mode };
        if (mode === 'single') {
            const api = document.getElementById('apiSelect').value;
            if (!api) { updateStatus('请选择接口'); return; }
            body.api = api;
            body.category = document.getElementById('categorySelect').value;
        }
        
        fetch('/api/video/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        }).then(r => r.json()).then(data => {
            videoList = data.results;
            videoTotalPages = data.total_pages || 1;
            renderVideoResults();
            updateStatus(`找到 ${data.results.length} 个影视`);
            document.getElementById('episodePanel').style.display = 'none';
            renderVideoPagination();
        }).catch(e => updateStatus('搜索失败: ' + e.message));
    }
    
    function browseCategory() {
        const api = document.getElementById('apiSelect').value;
        const category = document.getElementById('categorySelect').value;
        if (!api) { updateStatus('请选择接口'); return; }
        if (!category) { updateStatus('请选择分类'); return; }
        currentApi = api;
        currentCategory = category;
        videoCurrentPage = 1;
        loadBrowsePage();
    }
    
    function loadBrowsePage() {
        updateStatus(`浏览中 第${videoCurrentPage}页...`);
        fetch(`/api/video/browse?api=${encodeURIComponent(currentApi)}&category=${encodeURIComponent(currentCategory)}&page=${videoCurrentPage}`)
            .then(r => r.json()).then(data => {
                videoList = data.results;
                videoTotalPages = data.total_pages;
                renderVideoResults();
                renderVideoPagination();
                updateStatus(`第${videoCurrentPage}/${videoTotalPages}页`);
                document.getElementById('episodePanel').style.display = 'none';
            }).catch(e => updateStatus('浏览失败: ' + e.message));
    }
    
    function renderVideoResults() {
        const container = document.getElementById('videoResults');
        if (videoList.length === 0) {
            container.innerHTML = '<div class="status-bar">暂无结果</div>';
            return;
        }
        container.innerHTML = videoList.map((video, idx) => `
            <div class="list-item" onclick="openVideoPage(${idx})">
                <div class="item-name">
                    🎬 ${video.name}
                    <span class="play-icon">▶</span>
                </div>
                <div class="item-meta">
                    📡 ${video.source} | ${video.episode_count || 0}集
                    <button class="btn-sm" onclick="event.stopPropagation(); addToFavorites(${idx})">⭐ 收藏</button>
                </div>
            </div>
        `).join('');
    }

    function openVideoPage(idx) {
        const video = videoList[idx];
        if (!video) {
            updateStatus('视频不存在');
            return;
        }
        
        // 检查是否有剧集数据
        if (video.episodes && video.episodes.length > 0) {
            // 有数据，直接存入 sessionStorage
            sessionStorage.setItem('currentVideoData', JSON.stringify({
                name: video.name,
                source: video.source,
                episodes: video.episodes
            }));
            window.open(`/player?mode=series&video=${encodeURIComponent(video.name)}&source=${encodeURIComponent(video.source)}&fromCache=true`, '_blank');
        } else {
            // 没有数据，先获取再打开
            updateStatus('获取剧集信息...');
            fetch('/api/video/detail', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: video.source, name: video.name })
            }).then(r => r.json()).then(data => {
                if (data.episodes && data.episodes.length > 0) {
                    sessionStorage.setItem('currentVideoData', JSON.stringify({
                        name: video.name,
                        source: video.source,
                        episodes: data.episodes
                    }));
                    window.open(`/player?mode=series&video=${encodeURIComponent(video.name)}&source=${encodeURIComponent(video.source)}&fromCache=true`, '_blank');
                    updateStatus(`打开: ${video.name}`);
                } else {
                    updateStatus('暂无剧集');
                }
            }).catch(e => updateStatus('获取失败: ' + e.message));
        }
    }
    
    function renderVideoPagination() {
        const container = document.getElementById('videoPagination');
        if (videoTotalPages <= 1) { container.innerHTML = ''; return; }
        let html = `<button onclick="videoPrevPage()" ${videoCurrentPage<=1?'disabled':''}>◀</button>`;
        html += `<span style="padding:0 12px;">${videoCurrentPage}/${videoTotalPages}</span>`;
        html += `<button onclick="videoNextPage()" ${videoCurrentPage>=videoTotalPages?'disabled':''}>▶</button>`;
        container.innerHTML = html;
    }
    
    function videoPrevPage() { if (videoCurrentPage>1) { videoCurrentPage--; loadBrowsePage(); } }
    function videoNextPage() { if (videoCurrentPage<videoTotalPages) { videoCurrentPage++; loadBrowsePage(); } }
    
    function loadVideoEpisodes(idx) {
        const video = videoList[idx];
        currentVideoName = video.name;
        if (video.episodes && video.episodes.length > 0) {
            currentEpisodes = video.episodes;
            displayEpisodes();
        } else {
            updateStatus('加载剧集中...');
            fetch('/api/video/detail', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: video.source, name: video.name })
            }).then(r => r.json()).then(data => {
                currentEpisodes = data.episodes;
                displayEpisodes();
                updateStatus(`加载 ${data.episodes.length} 集`);
            }).catch(e => updateStatus('加载失败'));
        }
    }
    
    function displayEpisodes() {
        document.getElementById('currentVideoName').innerText = currentVideoName;
        document.getElementById('episodeCount').innerText = `(${currentEpisodes.length}集)`;
        const container = document.getElementById('episodeList');
        if (currentEpisodes.length === 0) {
            container.innerHTML = '<div>暂无剧集</div>';
        } else {
            container.innerHTML = currentEpisodes.map((ep, i) => 
                `<div class="episode-btn" onclick="playVideo(${i})">▶ ${ep.name}</div>`
            ).join('');
        }
        document.getElementById('episodePanel').style.display = 'block';
    }
    
    function playVideo(idx) {
        const episode = currentEpisodes[idx];
        if (!episode || !episode.url) { updateStatus('播放地址无效'); return; }
        const title = encodeURIComponent(`${currentVideoName} - ${episode.name}`);
        window.open(`/player?url=${encodeURIComponent(episode.url)}&title=${title}`, '_blank');
        updateStatus(`在新标签页播放: ${episode.name}`);
    }

// ==================== 收藏功能 ====================
function addToFavorites(idx) {
    const video = videoList[idx];
    if (!video) {
        updateStatus('视频不存在');
        return;
    }
    updateStatus('添加收藏中...');
    fetch('/api/favorites/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: video.name,
            source: video.source,
            episode_count: video.episode_count || 0
        })
    }).then(r => r.json()).then(data => {
        updateStatus(data.message);
    }).catch(e => updateStatus('添加失败: ' + e.message));
}

function loadFavorites() {
    updateStatus('加载收藏...');
    fetch('/api/favorites/get').then(r => r.json()).then(data => {
        renderFavorites(data.favorites);
        updateStatus(`加载 ${data.favorites.length} 个收藏`);
    }).catch(e => updateStatus('加载失败: ' + e.message));
}

function renderFavorites(favorites) {
    const container = document.getElementById('favoritesResults');
    if (favorites.length === 0) {
        container.innerHTML = '<div class="status-bar">暂无收藏，去影视搜索添加吧~</div>';
        return;
    }
    container.innerHTML = favorites.map((item, idx) => `
        <div class="list-item" onclick="playFavorite(${idx})">
            <div class="item-name">⭐ ${item.name}</div>
            <div class="item-meta">
                📡 ${item.source} | ${item.episode_count || 0}集 | 📅 ${item.add_time}
                <button class="btn-sm" onclick="event.stopPropagation(); removeFavorite('${escapeHtml(item.name)}', '${escapeHtml(item.source)}')">❌ 删除</button>
            </div>
        </div>
    `).join('');
}

function playFavorite(idx) {
    fetch('/api/favorites/get').then(r => r.json()).then(data => {
        const item = data.favorites[idx];
        if (item) {
            // 先搜索获取剧集数据再打开
            updateStatus(`获取: ${item.name}`);
            fetch('/api/video/detail', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: item.source, name: item.name })
            }).then(r => r.json()).then(data => {
                if (data.episodes && data.episodes.length > 0) {
                    sessionStorage.setItem('currentVideoData', JSON.stringify({
                        name: item.name,
                        source: item.source,
                        episodes: data.episodes
                    }));
                    window.open(`/player?mode=series&video=${encodeURIComponent(item.name)}&source=${encodeURIComponent(item.source)}&fromCache=true`, '_blank');
                    updateStatus(`播放: ${item.name}`);
                } else {
                    updateStatus('暂无剧集');
                }
            }).catch(e => updateStatus('获取失败'));
        }
    });
}

function removeFavorite(name, source) {
    fetch('/api/favorites/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, source: source })
    }).then(r => r.json()).then(data => {
        updateStatus(data.message);
        loadFavorites(); // 刷新列表
    });
}

function clearAllFavorites() {
    if (confirm('确定清空全部收藏吗？')) {
        fetch('/api/favorites/clear', { method: 'POST' }).then(r => r.json()).then(data => {
            updateStatus(data.message);
            loadFavorites();
        });
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
    
    // ==================== 工具 ====================
    function detectLinks() {
        const content = document.getElementById('detectUrls').value;
        if (!content.trim()) { updateStatus('请输入链接'); return; }
        updateStatus('检测中...');
        fetch('/api/tools/detect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        }).then(r => r.json()).then(data => {
            let html = `<div class="status-bar">✅ 有效: ${data.stats.valid} | ❌ 无效: ${data.stats.invalid}</div>`;
            if (data.valid.length) {
                html += `<div style="margin-top:8px;"><strong>有效链接:</strong><br>`;
                html += data.valid.slice(0,8).map(l => '• ' + (l.length>70 ? l.substring(0,70)+'...' : l)).join('<br>');
                html += `</div>`;
            }
            document.getElementById('detectResult').innerHTML = html;
            updateStatus(`检测完成`);
        });
    }
    
    function convertM3U(type) {
        const content = document.getElementById('convertContent').value;
        if (!content.trim()) { updateStatus('请输入内容'); return; }
        fetch('/api/tools/convert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, type })
        }).then(r => r.json()).then(data => {
            document.getElementById('convertResult').innerHTML = `
                <textarea style="width:100%; min-height:120px; font-size:11px;" readonly>${data.result}</textarea>
                <button onclick="copyText(this.previousElementSibling.value)">📋 复制</button>
            `;
            updateStatus(`转换完成`);
        });
    }
    
    function copyText(text) {
        navigator.clipboard.writeText(text);
        updateStatus('已复制');
    }
    
    function updateStatus(msg) {
        document.getElementById('globalStatus').innerHTML = `📡 ${msg}`;
    }
</script>
</body>
</html>
'''

PLAYER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - 播放器</title>
    <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet">
    <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #000; min-height: 100vh; display: flex; justify-content: center; align-items: center; font-family: system-ui; }
        .player-wrapper { width: 100%; max-width: 1200px; padding: 15px; }
        .video-js { width: 100%; aspect-ratio: 16/9; border-radius: 12px; }
        .info { color: #888; text-align: center; margin-top: 12px; font-size: 12px; }
        .back-btn { display: inline-block; margin-top: 15px; padding: 8px 20px; background: #e94560; color: white; text-decoration: none; border-radius: 8px; font-size: 13px; }
    </style>
</head>
<body>
<div class="player-wrapper">
    <video id="player" class="video-js vjs-big-play-centered" controls preload="auto"></video>
    <div class="info">
        <div>{{ title }}</div>
        <a href="javascript:history.back()" class="back-btn">← 返回</a>
    </div>
</div>
<script>
    const url = decodeURIComponent("{{ url|safe }}");
    document.title = decodeURIComponent("{{ title|safe }}");
    const videoElement = document.getElementById('player');
    if (Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(url);
        hls.attachMedia(videoElement);
        hls.on(Hls.Events.MANIFEST_PARSED, () => videoElement.play().catch(e=>{}));
    } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
        videoElement.src = url;
        videoElement.play().catch(e=>{});
    } else {
        videoElement.src = url;
    }
    videojs(videoElement, { controls: true, autoplay: true, fluid: true, aspectRatio: '16:9' });
</script>
</body>
</html>
'''

SERIES_PLAYER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ video_name }} - 剧集播放器</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; font-family: system-ui; }
        .container { max-width: 1200px; margin: 0 auto; padding: 15px; }
        video { width: 100%; aspect-ratio: 16/9; border-radius: 12px; background: #000; }
        .info { color: #888; text-align: center; margin: 15px 0; }
        .episode-section { background: #1a1a2e; border-radius: 12px; padding: 15px; margin-top: 20px; }
        .episode-section h3 { color: #fff; margin-bottom: 12px; }
        .episode-list { display: flex; flex-wrap: wrap; gap: 8px; max-height: 300px; overflow-y: auto; padding-bottom: 10px; }
        .episode-btn { padding: 8px 16px; background: #0f3460; border-radius: 20px; cursor: pointer; color: white; font-size: 13px; }
        .episode-btn:hover { background: #667eea; }
        .episode-btn.active { background: #e94560; }
        .loading { text-align: center; padding: 20px; color: #aaa; }
    </style>
</head>
<body>
<div class="container">
    <video id="player" controls autoplay></video>
    <div class="info" id="currentTitle">{{ video_name }} - 加载中...</div>
    <div class="episode-section">
        <h3>📺 剧集列表 <span id="episodeCount"></span></h3>
        <div class="episode-list" id="episodeList"><div class="loading">加载中...</div></div>
    </div>
</div>

<script>
    const videoName = decodeURIComponent("{{ video_name|safe }}");
    const sourceName = decodeURIComponent("{{ source_name|safe }}");
    let episodes = [];
    let currentPlayer = null;
    
    // 从缓存读取
    try {
        const cached = sessionStorage.getItem('currentVideoData');
        if (cached) {
            const data = JSON.parse(cached);
            if (data.name === videoName && data.episodes && data.episodes.length > 0) {
                episodes = data.episodes;
                console.log("从缓存读取:", episodes.length, "集");
                renderUI();
            }
        }
    } catch(e) {}
    
    // 没有缓存则从后端获取
    if (episodes.length === 0) {
        fetch('/api/video/detail', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: sourceName, name: videoName })
        }).then(r => r.json()).then(data => {
            if (data.episodes && data.episodes.length > 0) {
                episodes = data.episodes;
                console.log("从后端获取:", episodes.length, "集");
                renderUI();
            } else {
                document.getElementById('episodeList').innerHTML = '<div class="loading">暂无剧集</div>';
                document.getElementById('currentTitle').innerText = videoName + ' - 暂无剧集';
            }
        }).catch(e => {
            console.error(e);
            document.getElementById('episodeList').innerHTML = '<div class="loading">加载失败</div>';
        });
    }
    
    function renderUI() {
        if (episodes.length === 0) return;
        
        document.getElementById('episodeCount').innerText = `(${episodes.length}集)`;
        document.getElementById('episodeList').innerHTML = episodes.map((ep, i) => 
            `<div class="episode-btn" data-idx="${i}" onclick="playEpisode(${i})">${ep.name || '第'+(i+1)+'集'}</div>`
        ).join('');
        
        // 播放第一集
        playEpisode(0);
    }
    
    function playEpisode(idx) {
        const ep = episodes[idx];
        if (!ep || !ep.url) {
            alert('播放地址无效');
            return;
        }
        
        console.log("播放:", ep.name || '第'+(idx+1)+'集');
        document.getElementById('currentTitle').innerText = `${videoName} - ${ep.name || '第'+(idx+1)+'集'}`;
        
        // 高亮当前选中
        document.querySelectorAll('.episode-btn').forEach((btn, i) => {
            if (i == idx) btn.classList.add('active');
            else btn.classList.remove('active');
        });
        
        // 原生 video 播放 m3u8（移动端 Safari/Chrome 都支持）
        const video = document.getElementById('player');
        video.src = ep.url;
        video.load();
        video.play().catch(e => console.log("自动播放被阻止:", e));
    }
</script>
</body>
</html>
'''


# ==================== Flask 路由 ====================
@app.route('/')
def index():
    return render_template_string(MAIN_TEMPLATE)

@app.route('/player')
def player():
    url = request.args.get('url', '')
    title = request.args.get('title', '视频播放')
    video_name = request.args.get('video', '')
    source_name = request.args.get('source', '')
    mode = request.args.get('mode', '')
    from_cache = request.args.get('fromCache', '')
    
    # 如果是剧集模式
    if mode == 'series' and video_name and source_name:
        return render_template_string(SERIES_PLAYER_TEMPLATE, 
                                     video_name=video_name, 
                                     source_name=source_name,
                                     from_cache=from_cache)
    
    return render_template_string(PLAYER_TEMPLATE, url=url, title=title)

@app.route('/api/local/songs')
def local_songs():
    songs = [{"name": f.replace('.mp3', ''), "url": f"/api/local/music/{f}"} for f in os.listdir(MUSIC_BASE) if f.endswith('.mp3')]
    return jsonify({"songs": songs})

@app.route('/api/local/music/<filename>')
def local_music(filename):
    filepath = os.path.join(MUSIC_BASE, filename)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='audio/mpeg')
    return "Not found", 404

@app.route('/api/music/status')
def music_status():
    return jsonify({"status": "✅ 运行中" if check_api_status() else "❌ 未启动"})

@app.route('/api/music/start')
def music_start():
    return jsonify({"message": start_api_service()})

@app.route('/api/music/search', methods=['POST'])
def music_search():
    data = request.json
    results = search_song(data.get('keyword', ''), filter_vip=data.get('filter_vip', True))
    return jsonify({"results": results})

@app.route('/api/music/download', methods=['POST'])
def music_download():
    data = request.json
    msg = download_song(data.get('title', '未知'), data.get('url', ''))
    return jsonify({"message": msg})

@app.route('/api/playlist/load')
def playlist_load():
    songs = []
    title = None
    if os.path.exists(M3U_PATH):
        with open(M3U_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    title = line.split(",", 1)[-1].strip()
                elif line and not line.startswith("#") and title:
                    songs.append({"name": title, "url": line})
                    title = None
    return jsonify({"songs": songs})

@app.route('/api/apis')
def get_apis():
    return jsonify([{"name": api["name"], "group": api.get("group", "其他")} for api in API_LIST if api.get("enabled")])

@app.route('/api/categories')
def get_categories():
    api_name = request.args.get('api')
    api_config = next((a for a in API_LIST if a["name"] == api_name), None)
    if not api_config:
        return jsonify([])
    return jsonify(fetch_categories(api_config))

@app.route('/api/video/search', methods=['POST'])
def video_search():
    data = request.json
    keyword = data.get('keyword', '')
    mode = data.get('mode', 'all')
    
    if mode == 'single':
        api_name = data.get('api')
        api_config = next((a for a in API_LIST if a["name"] == api_name), None)
        if not api_config:
            return jsonify({"results": [], "total_pages": 1})
        results, total_pages = search_single_api(api_config, keyword, data.get('category'), 1)
    else:
        results = []
        total_pages = 1
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
            futures = [executor.submit(search_single_api, api, keyword, None, 1) for api in API_LIST if api.get("enabled")]
            for future in as_completed(futures):
                try:
                    r, _ = future.result()
                    results.extend(r)
                except:
                    pass
        seen = set()
        unique = []
        for r in results:
            if r["name"] not in seen:
                seen.add(r["name"])
                unique.append(r)
        results = unique
    
    for r in results:
        r['episode_count'] = len(r.get('episodes', []))
    return jsonify({"results": results, "total_pages": total_pages})

@app.route('/api/video/browse')
def video_browse():
    api_name = request.args.get('api')
    category = request.args.get('category')
    page = int(request.args.get('page', 1))
    api_config = next((a for a in API_LIST if a["name"] == api_name), None)
    if not api_config:
        return jsonify({"results": [], "total_pages": 1})
    results, total_pages = search_single_api(api_config, "", category, page)
    for r in results:
        r['episode_count'] = len(r.get('episodes', []))
    return jsonify({"results": results, "total_pages": total_pages})

@app.route('/api/video/detail', methods=['POST'])
def video_detail():
    data = request.json
    source_name = data.get('source')
    video_name = data.get('name')
    api_config = next((a for a in API_LIST if a["name"] == source_name), None)
    if not api_config:
        return jsonify({"episodes": []})
    results, _ = search_single_api(api_config, video_name, None, 1)
    if results:
        return jsonify({"episodes": results[0].get('episodes', [])})
    return jsonify({"episodes": []})

@app.route('/api/tools/detect', methods=['POST'])
def tools_detect():
    content = request.json.get('content', '')
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    valid, invalid = [], []
    for line in lines:
        if '$' in line:
            _, url = line.split('$', 1)
        else:
            url = line
        if check_url_validity(url).get('valid'):
            valid.append(line)
        else:
            invalid.append(line)
    return jsonify({"valid": valid, "invalid": invalid, "stats": {"valid": len(valid), "invalid": len(invalid)}})

@app.route('/api/tools/export', methods=['POST'])
def tools_export():
    songs = request.json.get('songs', [])
    valid_lines = []
    for song in songs:
        if check_url_validity(song['url']).get('valid'):
            valid_lines.append(f"{song['name']}${song['url']}")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"music_valid_{timestamp}.txt"
    filepath = os.path.join(EXPORT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# 有效音乐链接 {len(valid_lines)}首\n")
        f.write(f"# 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for line in valid_lines:
            f.write(line + '\n')
    return jsonify({"file": filepath, "valid_count": len(valid_lines)})

@app.route('/api/tools/check', methods=['POST'])
def tools_check():
    data = request.json
    url = data.get('url', '')
    result = check_url_validity(url)
    return jsonify({"valid": result["valid"], "message": result["message"]})

# ==================== 收藏功能 ====================
def load_favorites():
    """加载收藏列表"""
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_favorites(favorites):
    """保存收藏列表"""
    try:
        os.makedirs(os.path.dirname(FAVORITES_FILE), exist_ok=True)
        with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存收藏失败: {e}")
        return False

@app.route('/api/favorites/get', methods=['GET'])
def get_favorites():
    """获取收藏列表"""
    return jsonify({"favorites": load_favorites()})

@app.route('/api/favorites/add', methods=['POST'])
def add_favorite():
    """添加收藏"""
    data = request.json
    favorites = load_favorites()
    name = data.get('name', '')
    source = data.get('source', '')
    
    # 检查是否已存在
    exists = any(f.get('name') == name and f.get('source') == source for f in favorites)
    if not exists:
        favorites.append({
            "name": name,
            "source": source,
            "episode_count": data.get('episode_count', 0),
            "add_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        save_favorites(favorites)
        return jsonify({"success": True, "message": "已添加收藏"})
    return jsonify({"success": False, "message": "已在收藏中"})

@app.route('/api/favorites/remove', methods=['POST'])
def remove_favorite():
    """移除收藏"""
    data = request.json
    favorites = load_favorites()
    name = data.get('name', '')
    source = data.get('source', '')
    favorites = [f for f in favorites if not (f.get('name') == name and f.get('source') == source)]
    save_favorites(favorites)
    return jsonify({"success": True, "message": "已移除收藏"})

@app.route('/api/favorites/clear', methods=['POST'])
def clear_favorites():
    """清空收藏"""
    save_favorites([])
    return jsonify({"success": True, "message": "已清空收藏"})

@app.route('/api/tools/convert', methods=['POST'])
def tools_convert():
    content = request.json.get('content', '')
    convert_type = request.json.get('type', 'toTxt')
    if convert_type == 'toTxt':
        result = convert_a_to_b(content)
    else:
        result = convert_b_to_a(content)
    return jsonify({"result": result})

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("\n" + "=" * 50)
    print("   🎵 影音工具箱 - 手机版")
    print("=" * 50)
    print(f"   📁 音乐目录: {MUSIC_BASE}")
    print(f"   📁 导出目录: {EXPORT_DIR}")
    print(f"   📁 配置文件: {CONFIG_FILE}")
    print(f"   🌐 访问: http://{local_ip}:5000")
    print("=" * 50)
    print("   Ctrl+C 停止服务\n")
    
    def open_browser():
        time.sleep(1)
        webbrowser.open('http://127.0.0.1:5000')
    threading.Thread(target=open_browser, daemon=True).start()
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)