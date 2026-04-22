# web_video_tool.py - 网页版影视搜索工具（播放器自动展开版）
import os
import json
import time
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from flask import Flask, request, jsonify, render_template_string

# ==================== 配置加载 ====================

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


CONFIG = load_config()
API_LIST = CONFIG.get("api_list", [])
REQUEST_TIMEOUT = CONFIG.get("request_timeout", 10)
MAX_CONCURRENT = CONFIG.get("max_concurrent", 5)
USER_AGENT = CONFIG.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
PAGE_SIZE = CONFIG.get("page_size", 50)

HEALTH_FILE = os.path.join(os.path.dirname(__file__), "api_health.json")


def load_health_records():
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def save_health_records(records):
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except:
        pass


def test_api_speed(api_config):
    if not api_config.get("enabled", True):
        return -1
    url = api_config["url"]
    params = {"ac": "videolist", "pg": 1, "pagesize": 1}
    try:
        start = time.time()
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            return round((time.time() - start) * 1000, 0)
    except:
        pass
    return -1


# ==================== 解析模块 ====================

def build_api_url(api_config):
    url = api_config["url"]
    if not url.endswith('/'):
        url = url + '/'
    if api_config.get("format") == 'xml':
        if not url.endswith('xml/'):
            url = url + 'at/xml/'
    elif api_config.get("format") == 'json':
        if not url.endswith('json/'):
            url = url + 'at/json/'
    return url


def extract_episodes_from_string(text):
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


def detect_format(text):
    if not text:
        return 'unknown'
    text_stripped = text.strip()
    if text_stripped.startswith('<?xml') or text_stripped.startswith('<rss'):
        return 'xml'
    for ch in text_stripped:
        if ch == '{' or ch == '[':
            return 'json'
        elif not ch.isspace():
            break
    if '"code":' in text or '"list":' in text:
        return 'json'
    return 'unknown'


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
                    episodes = extract_episodes_from_string(dd.text)
                    if episodes:
                        break
            if name and episodes:
                videos.append({"name": name, "episodes": episodes, "source": source_name})
    except Exception as e:
        print(f"解析错误: {e}")
    return videos


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
            if play_url:
                episodes = extract_episodes_from_string(play_url)
            else:
                episodes = []
            if name and episodes:
                videos.append({"name": name, "episodes": episodes, "source": source_name})
    except Exception as e:
        print(f"解析错误: {e}")
    return videos


def get_categories_from_api(api_config):
    url = build_api_url(api_config)
    params = {"ac": "list"}
    try:
        response_text = http_get(url, params=params)
        if not response_text:
            return []
        fmt = detect_format(response_text)
        categories = []
        if fmt == 'xml':
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response_text)
            for class_node in root.findall('.//class'):
                type_id = class_node.find('type_id')
                type_name = class_node.find('type_name')
                if type_id is not None and type_name is not None:
                    categories.append({"id": type_id.text, "name": type_name.text})
        elif fmt == 'json':
            data = json.loads(response_text)
            class_list = data.get('class', data.get('list', []))
            for item in class_list:
                cid = item.get('type_id', item.get('id', ''))
                cname = item.get('type_name', item.get('name', ''))
                if cid and cname:
                    categories.append({"id": cid, "name": cname})
        return categories
    except Exception as e:
        print(f"获取分类失败: {e}")
        return []


def http_get(url, params=None, headers=None):
    default_headers = {'User-Agent': USER_AGENT}
    if headers:
        default_headers.update(headers)
    try:
        response = requests.get(url, params=params, headers=default_headers, timeout=REQUEST_TIMEOUT)
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"请求失败: {e}")
        return None


def search_single_api(api_config, keyword, category_id=None):
    if not api_config.get("enabled", True):
        return []
    videos = []
    source_name = api_config["name"]
    url = build_api_url(api_config)
    try:
        if api_config.get("searchable", True):
            params = {"ac": "videolist", "wd": keyword, "pg": 1, "pagesize": PAGE_SIZE}
        else:
            params = {"ac": "videolist", "pg": 1, "pagesize": PAGE_SIZE * 2}
        if category_id:
            params["t"] = category_id
        response_text = http_get(url, params=params)
        if not response_text:
            return []
        fmt = detect_format(response_text)
        if fmt == 'xml':
            parsed = parse_xml_videos(response_text, source_name)
        elif fmt == 'json':
            parsed = parse_json_videos(response_text, source_name)
        else:
            return []
        for item in parsed:
            episodes = item.get('episodes', [])
            name = item.get('name', '')
            if episodes and name:
                if not api_config.get("searchable", True):
                    if keyword.lower() not in name.lower():
                        continue
                videos.append({"name": name, "episodes": episodes, "source": source_name})
        return videos
    except Exception as e:
        print(f"搜索失败 {source_name}: {e}")
        return []


def search_all_apis(keyword, api_list=None, category_id=None):
    if api_list is None:
        api_list = [api for api in API_LIST if api.get("enabled", True)]
    all_results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = {executor.submit(search_single_api, api, keyword, category_id): api for api in api_list}
        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except:
                pass
    seen = set()
    unique = []
    for r in all_results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique


# ==================== Flask 应用 ====================

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>影视搜索工具</title>
    <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet">
    <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 16px; background: #1a1a2e; color: #eee; }
        .container { max-width: 1400px; margin: 0 auto; }
        .search-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; background: #16213e; padding: 12px; border-radius: 12px; }
        .search-bar input, .search-bar select { padding: 10px 12px; border-radius: 8px; border: 1px solid #0f3460; background: #0f3460; color: #eee; font-size: 14px; }
        .search-bar input { flex: 2; min-width: 150px; }
        .search-bar select { background: #0f3460; }
        .search-bar button { padding: 10px 20px; border-radius: 8px; border: none; background: #e94560; color: white; cursor: pointer; font-weight: bold; }
        .search-bar button:hover { background: #ff6b6b; }
        .mode-group { display: flex; gap: 4px; background: #0f3460; border-radius: 8px; padding: 2px; }
        .mode-btn { padding: 8px 16px; border-radius: 6px; cursor: pointer; background: transparent; color: #eee; border: none; }
        .mode-btn.active { background: #e94560; }
        .result-table { width: 100%; overflow-x: auto; background: #16213e; border-radius: 12px; padding: 12px; margin-bottom: 16px; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { padding: 10px 8px; text-align: left; border-bottom: 1px solid #0f3460; }
        th { cursor: pointer; color: #e94560; }
        th:hover { background: #0f3460; }
        .video-item { cursor: pointer; }
        .video-item:hover { background: #0f3460; }
        .episode-panel { background: #16213e; border-radius: 12px; padding: 12px; margin-bottom: 16px; }
        .episode-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; max-height: 200px; overflow-y: auto; }
        .episode-btn { padding: 8px 16px; border-radius: 20px; background: #0f3460; cursor: pointer; font-size: 13px; }
        .episode-btn:hover { background: #e94560; }
        .player-container { 
            background: #000; 
            border-radius: 12px; 
            overflow: hidden;
            transition: all 0.3s ease;
            margin-top: 16px;
        }
        .player-container.collapsed {
            max-height: 0;
            margin: 0;
            opacity: 0;
            overflow: hidden;
        }
        .player-container.expanded {
            max-height: 600px;
            opacity: 1;
        }
        .pagination { display: flex; gap: 10px; justify-content: center; margin-top: 16px; flex-wrap: wrap; }
        .pagination button { padding: 8px 16px; background: #0f3460; border: none; border-radius: 8px; color: #eee; cursor: pointer; }
        .status-bar { background: #0f3460; padding: 8px 12px; border-radius: 8px; margin-top: 16px; font-size: 13px; color: #aaa; }
        .loading { text-align: center; padding: 20px; color: #aaa; }
        @media (max-width: 768px) { body { padding: 8px; } th, td { font-size: 12px; padding: 6px 4px; } .episode-btn { padding: 6px 12px; font-size: 11px; } }
    </style>
</head>
<body>
<div class="container">
    <div class="search-bar">
        <input type="text" id="keyword" placeholder="搜索关键词..." onkeypress="if(event.keyCode==13) search()">
        <div class="mode-group" id="modeGroup">
            <button class="mode-btn active" data-mode="all">🔍 聚合</button>
            <button class="mode-btn" data-mode="single">📡 单接口</button>
            <button class="mode-btn" data-mode="group">📁 组内</button>
        </div>
        <select id="apiSelect" style="display:none"></select>
        <select id="groupSelect" style="display:none"></select>
        <select id="categorySelect" style="display:none"></select>
        <button onclick="browse()">浏览</button>
        <button onclick="search()">搜索</button>
        <button onclick="testSpeed()">⏱️ 测速</button>
    </div>
    
    <div class="result-table">
        <div style="overflow-x: auto;">
            <table id="resultTable">
                <thead><tr>
                    <th onclick="sortTable('name')">名称</th>
                    <th onclick="sortTable('episodes')">集数</th>
                    <th onclick="sortTable('source')">来源</th>
                    <th onclick="sortTable('speed')">速度(ms)</th>
                </tr></thead>
                <tbody id="resultBody"><tr><td colspan="4" class="loading">请输入关键词搜索<\/td></tr></tbody>
            </table>
        </div>
        <div class="pagination" id="pagination"></div>
    </div>
    
    <div class="episode-panel" id="episodePanel" style="display:none">
        <div><strong id="currentVideoName"></strong> <span id="episodeCount"></span></div>
        <div class="episode-list" id="episodeList"></div>
    </div>
    
    <div class="player-container collapsed" id="playerContainer">
        <video id="player" class="video-js vjs-big-play-centered" controls preload="auto" width="100%" height="auto"></video>
    </div>
    
    <div class="status-bar" id="statusBar">就绪</div>
</div>

<script>
    let currentResults = [];
    let currentEpisodes = [];
    let currentVideoName = "";
    let currentPage = 1;
    let totalPages = 1;
    let currentApi = "";
    let currentCategory = "";
    let categories = [];
    let sortField = "name";
    let sortReverse = false;
    
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateModeUI();
        };
    });
    
    function updateModeUI() {
        const mode = document.querySelector('.mode-btn.active').dataset.mode;
        document.getElementById('apiSelect').style.display = mode === 'single' ? 'inline-block' : 'none';
        document.getElementById('groupSelect').style.display = mode === 'group' ? 'inline-block' : 'none';
        if (mode === 'single') loadApis();
        else if (mode === 'group') loadGroups();
        // 收起播放器
        const pc = document.getElementById('playerContainer');
        pc.classList.add('collapsed');
        pc.classList.remove('expanded');
    }
    
    function loadApis() {
        fetch('/api/apis').then(r => r.json()).then(data => {
            const select = document.getElementById('apiSelect');
            select.innerHTML = data.map(api => `<option value="${api.name}">${api.name}</option>`).join('');
            select.onchange = () => loadCategories();
            loadCategories();
        });
    }
    
    function loadGroups() {
        fetch('/api/groups').then(r => r.json()).then(data => {
            const select = document.getElementById('groupSelect');
            select.innerHTML = data.map(g => `<option value="${g}">${g}</option>`).join('');
        });
    }
    
    function loadCategories() {
        const api = document.getElementById('apiSelect').value;
        if (!api) return;
        fetch(`/api/categories?api=${encodeURIComponent(api)}`).then(r => r.json()).then(data => {
            categories = data;
            const select = document.getElementById('categorySelect');
            select.style.display = 'inline-block';
            select.innerHTML = '<option value="">全部</option>' + data.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        });
    }
    
    function search() {
        const keyword = document.getElementById('keyword').value.trim();
        if (!keyword) { updateStatus("请输入关键词"); return; }
        const mode = document.querySelector('.mode-btn.active').dataset.mode;
        let api = '', group = '', category = '';
        if (mode === 'single') { api = document.getElementById('apiSelect').value; category = document.getElementById('categorySelect').value; }
        else if (mode === 'group') group = document.getElementById('groupSelect').value;
        updateStatus("搜索中...");
        fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, mode, api, group, category })
        }).then(r => r.json()).then(data => {
            currentResults = data.results;
            currentPage = 1;
            totalPages = 1;
            renderResults();
            updateStatus(`找到 ${currentResults.length} 个结果`);
            document.getElementById('episodePanel').style.display = 'none';
            const pc = document.getElementById('playerContainer');
            pc.classList.add('collapsed');
            pc.classList.remove('expanded');
        });
    }
    
    function browse() {
        const mode = document.querySelector('.mode-btn.active').dataset.mode;
        if (mode !== 'single') { updateStatus("请切换到「单接口」模式"); return; }
        const api = document.getElementById('apiSelect').value;
        const category = document.getElementById('categorySelect').value;
        if (!category) { updateStatus("请选择分类"); return; }
        currentApi = api;
        currentCategory = category;
        currentPage = 1;
        loadBrowsePage();
    }
    
    function loadBrowsePage() {
        updateStatus(`浏览中... 第${currentPage}页`);
        fetch(`/api/browse?api=${encodeURIComponent(currentApi)}&category=${encodeURIComponent(currentCategory)}&page=${currentPage}`)
            .then(r => r.json()).then(data => {
                currentResults = data.results;
                totalPages = data.total_pages;
                renderResults();
                renderPagination();
                updateStatus(`第${currentPage}页，共${totalPages}页`);
                document.getElementById('episodePanel').style.display = 'none';
                const pc = document.getElementById('playerContainer');
                pc.classList.add('collapsed');
                pc.classList.remove('expanded');
            });
    }
    
    function renderPagination() {
        const container = document.getElementById('pagination');
        if (totalPages <= 1) { container.innerHTML = ''; return; }
        let html = `<button onclick="prevPage()" ${currentPage<=1?'disabled':''}>◀ 上一页</button>`;
        html += `<span style="padding:0 16px">第 ${currentPage} / ${totalPages} 页</span>`;
        html += `<button onclick="nextPage()" ${currentPage>=totalPages?'disabled':''}>下一页 ▶</button>`;
        html += `<input type="number" id="jumpPage" style="width:60px;margin-left:10px">`;
        html += `<button onclick="jumpPage()">跳转</button>`;
        container.innerHTML = html;
    }
    
    function prevPage() { if (currentPage > 1) { currentPage--; loadBrowsePage(); } }
    function nextPage() { if (currentPage < totalPages) { currentPage++; loadBrowsePage(); } }
    function jumpPage() { let p = parseInt(document.getElementById('jumpPage').value); if (p>=1 && p<=totalPages) { currentPage=p; loadBrowsePage(); } }
    
    function renderResults() {
        let results = [...currentResults];
        if (sortField === 'name') results.sort((a,b) => sortReverse ? b.name.localeCompare(a.name) : a.name.localeCompare(b.name));
        else if (sortField === 'episodes') results.sort((a,b) => sortReverse ? b.episode_count - a.episode_count : a.episode_count - b.episode_count);
        else if (sortField === 'source') results.sort((a,b) => sortReverse ? b.source.localeCompare(a.source) : a.source.localeCompare(b.source));
        else if (sortField === 'speed') results.sort((a,b) => sortReverse ? b.speed - a.speed : a.speed - b.speed);
        
        const tbody = document.getElementById('resultBody');
        if (results.length === 0) { tbody.innerHTML = '<tr><td colspan="4" class="loading">暂无数据<\/td><\/tr>'; return; }
        tbody.innerHTML = results.map((v, i) => `
            <tr class="video-item" onclick="loadEpisodes(${i})">
                <td>${v.name}<\/td>
                <td>${v.episode_count || 0}集<\/td>
                <td>${v.source}<\/td>
                <td>${v.speed || '未测'}<\/td>
             <\/tr>
        `).join('');
    }
    
    function loadEpisodes(idx) {
        const video = currentResults[idx];
        currentVideoName = video.name;
        
        if (video.episodes && video.episodes.length > 0) {
            currentEpisodes = video.episodes;
            displayEpisodes();
            return;
        }
        
        updateStatus("加载剧集中...");
        fetch('/api/detail', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: video.source, name: video.name })
        }).then(r => r.json()).then(data => {
            if (data.episodes && data.episodes.length > 0) {
                video.episodes = data.episodes;
                currentEpisodes = data.episodes;
                displayEpisodes();
                updateStatus(`已加载 ${data.episodes.length} 集`);
            } else {
                updateStatus("未找到剧集信息");
                document.getElementById('episodeList').innerHTML = '<div>未找到剧集信息</div>';
                document.getElementById('episodePanel').style.display = 'block';
                // 收起播放器
                const pc = document.getElementById('playerContainer');
                pc.classList.add('collapsed');
                pc.classList.remove('expanded');
            }
        }).catch(e => {
            updateStatus("加载失败: " + e.message);
        });
    }
    
    function displayEpisodes() {
        document.getElementById('currentVideoName').innerText = currentVideoName;
        document.getElementById('episodeCount').innerText = `(${currentEpisodes.length}集)`;
        const container = document.getElementById('episodeList');
        if (currentEpisodes.length === 0) {
            container.innerHTML = '<div>暂无剧集信息</div>';
        } else {
            container.innerHTML = currentEpisodes.map((ep, i) => 
                `<div class="episode-btn" onclick="playEpisode(${i})">${ep.name}</div>`
            ).join('');
        }
        document.getElementById('episodePanel').style.display = 'block';
        // 收起播放器
        const pc = document.getElementById('playerContainer');
        pc.classList.add('collapsed');
        pc.classList.remove('expanded');
    }
    
    function playEpisode(idx) {
        const episode = currentEpisodes[idx];
        const url = episode.url;
        if (!url) { updateStatus("播放地址无效"); return; }
        updateStatus(`播放: ${currentVideoName} - ${episode.name}`);
        
        // 展开播放器
        const pc = document.getElementById('playerContainer');
        pc.classList.remove('collapsed');
        pc.classList.add('expanded');
        
        const videoElement = document.getElementById('player');
        if (window.currentPlayer) window.currentPlayer.dispose();
        
        if (Hls.isSupported()) {
            const hls = new Hls();
            hls.loadSource(url);
            hls.attachMedia(videoElement);
            hls.on(Hls.Events.MANIFEST_PARSED, () => videoElement.play());
        } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
            videoElement.src = url;
            videoElement.play();
        } else {
            videoElement.src = url;
        }
        
        window.currentPlayer = videojs(videoElement, { 
            controls: true, 
            autoplay: true,
            fluid: true,
            aspectRatio: '16:9'
        });
        
        // 滚动到播放器
        pc.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    function sortTable(field) {
        if (sortField === field) sortReverse = !sortReverse;
        else { sortField = field; sortReverse = false; }
        renderResults();
    }
    
    function testSpeed() {
        updateStatus("测速中...");
        fetch('/api/speed_test').then(r => r.json()).then(data => {
            updateStatus("测速完成");
            location.reload();
        });
    }
    
    function updateStatus(msg) {
        document.getElementById('statusBar').innerText = msg;
    }
    
    updateModeUI();
</script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/apis')
def get_apis():
    apis = [{"name": api["name"]} for api in API_LIST if api.get("enabled", True)]
    return jsonify(apis)


@app.route('/api/groups')
def get_groups():
    groups = set()
    for api in API_LIST:
        if api.get("enabled", True):
            group = api.get("group", "未分组")
            groups.add(group)
    return jsonify(sorted(list(groups)))


@app.route('/api/categories')
def get_categories():
    api_name = request.args.get('api')
    api_config = None
    for api in API_LIST:
        if api.get("name") == api_name:
            api_config = api
            break
    if not api_config:
        return jsonify([])
    categories = get_categories_from_api(api_config)
    return jsonify(categories)


@app.route('/api/search', methods=['POST'])
def search_api():
    data = request.json
    keyword = data.get('keyword', '')
    mode = data.get('mode', 'all')
    api_name = data.get('api', '')
    group_name = data.get('group', '')
    category_id = data.get('category', '')
    
    if mode == 'single':
        apis = [api for api in API_LIST if api.get("name") == api_name and api.get("enabled", True)]
    elif mode == 'group':
        apis = [api for api in API_LIST if api.get("group") == group_name and api.get("enabled", True)]
    else:
        apis = [api for api in API_LIST if api.get("enabled", True)]
    
    results = search_all_apis(keyword, apis, category_id if category_id else None)
    
    records = load_health_records()
    for r in results:
        speed = records.get(r['source'], {}).get('speed', -1)
        r['speed'] = f"{speed:.0f}" if speed > 0 else "未测"
        r['episode_count'] = len(r.get('episodes', []))
    
    return jsonify({"results": results})


@app.route('/api/browse')
def browse_api():
    api_name = request.args.get('api')
    category_id = request.args.get('category')
    page = int(request.args.get('page', 1))
    
    api_config = None
    for api in API_LIST:
        if api.get("name") == api_name:
            api_config = api
            break
    if not api_config:
        return jsonify({"results": [], "total_pages": 1})
    
    url = build_api_url(api_config)
    params = {"ac": "videolist", "pg": page, "pagesize": 30, "t": category_id}
    
    try:
        response_text = http_get(url, params=params)
        if not response_text:
            return jsonify({"results": [], "total_pages": 1})
        
        fmt = detect_format(response_text)
        if fmt == 'xml':
            videos = parse_xml_videos(response_text, api_config["name"])
        elif fmt == 'json':
            videos = parse_json_videos(response_text, api_config["name"])
        else:
            return jsonify({"results": [], "total_pages": 1})
        
        total_pages = 1
        if fmt == 'xml':
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(response_text)
                list_node = root.find('list')
                if list_node is not None and list_node.get('pagecount'):
                    total_pages = int(list_node.get('pagecount'))
            except:
                pass
        elif fmt == 'json':
            try:
                data = json.loads(response_text)
                total_pages = data.get('pagecount', data.get('total_pages', 1))
            except:
                pass
        
        records = load_health_records()
        for v in videos:
            speed = records.get(v['source'], {}).get('speed', -1)
            v['speed'] = f"{speed:.0f}" if speed > 0 else "未测"
            v['episode_count'] = len(v.get('episodes', []))
        
        return jsonify({"results": videos, "total_pages": total_pages})
    except Exception as e:
        return jsonify({"results": [], "total_pages": 1, "error": str(e)})


@app.route('/api/detail', methods=['POST'])
def detail_api():
    data = request.json
    source_name = data.get('source')
    video_name = data.get('name')
    
    api_config = None
    for api in API_LIST:
        if api.get("name") == source_name:
            api_config = api
            break
    
    if not api_config:
        return jsonify({"episodes": []})
    
    results = search_all_apis(video_name, [api_config])
    
    if results and len(results) > 0:
        episodes = results[0].get('episodes', [])
        return jsonify({"episodes": episodes})
    
    return jsonify({"episodes": []})


@app.route('/api/speed_test')
def speed_test_api():
    def do_test():
        records = load_health_records()
        for api in API_LIST:
            if not api.get("enabled", True):
                continue
            speed = test_api_speed(api)
            if api["name"] not in records:
                records[api["name"]] = {}
            records[api["name"]]["speed"] = speed
            records[api["name"]]["last_check"] = datetime.now().isoformat()
            records[api["name"]]["alive"] = speed > 0
        save_health_records(records)
    
    threading.Thread(target=do_test, daemon=True).start()
    return jsonify({"status": "ok"})


@app.route('/api/status')
def status_api():
    return jsonify({"message": f"就绪 - {datetime.now().strftime('%H:%M:%S')}"})


def get_local_ip():
    import socket
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
    print("  影视搜索工具 - 网页版已启动")
    print("=" * 50)
    print(f"  本地访问: http://127.0.0.1:5000")
    print(f"  局域网访问: http://{local_ip}:5000")
    print("  手机访问：确保手机连接同一WiFi，输入上面局域网地址")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)