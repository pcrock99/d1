# video_tool.py - 影视搜索工具完整版（支持分组搜索 + 测速 + 健康检查 + 分类筛选 + 分页浏览）
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
import json
import re
import subprocess
import sys
import atexit
import tempfile
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

import requests


# ==================== 配置加载 ====================

def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("配置文件 config.json 不存在，使用默认配置")
        return {}
    except json.JSONDecodeError as e:
        print(f"配置文件格式错误: {e}")
        return {}


CONFIG = load_config()

# 接口列表
API_LIST = CONFIG.get("api_list", [])

# 播放器配置
MPV_PATH = CONFIG.get("mpv_path", "mpv")

# 请求配置
REQUEST_TIMEOUT = CONFIG.get("request_timeout", 10)
MAX_CONCURRENT = CONFIG.get("max_concurrent", 5)
USER_AGENT = CONFIG.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

# 搜索配置
PAGE_SIZE = CONFIG.get("page_size", 50)
MAX_PAGES = CONFIG.get("max_pages", 3)

# 广告过滤
ENABLE_AD_FILTER = CONFIG.get("enable_ad_filter", False)
AD_DOMAINS = CONFIG.get("ad_domains", [])

# 测速配置
SPEED_TEST_ENABLED = CONFIG.get("speed_test", {}).get("enabled", True)
SPEED_TEST_TIMEOUT = CONFIG.get("speed_test", {}).get("timeout", 5)

# 健康检查配置
HEALTH_CHECK_ENABLED = CONFIG.get("health_check", {}).get("enabled", True)
HEALTH_CHECK_INTERVAL = CONFIG.get("health_check", {}).get("interval_hours", 24)
HEALTH_CHECK_AUTO_DISABLE = CONFIG.get("health_check", {}).get("auto_disable", True)

# 健康检查记录文件
HEALTH_FILE = os.path.join(os.path.dirname(__file__), "api_health.json")


# ==================== 接口健康管理 ====================

def load_health_records() -> Dict:
    """加载健康检查记录"""
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_health_records(records: Dict):
    """保存健康检查记录"""
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存健康记录失败: {e}")


def test_api_speed(api_config: Dict) -> float:
    """测试单个接口的响应速度"""
    if not api_config.get("enabled", True):
        return -1
    
    url = api_config["url"]
    params = {"ac": "videolist", "pg": 1, "pagesize": 1}
    
    try:
        start = time.time()
        response = requests.get(url, params=params, timeout=SPEED_TEST_TIMEOUT)
        elapsed = time.time() - start
        
        if response.status_code == 200:
            return round(elapsed, 2)
        else:
            return -1
    except Exception:
        return -1


def check_api_health(api_config: Dict) -> Dict:
    """检查单个接口的健康状态"""
    result = {
        "name": api_config["name"],
        "alive": False,
        "speed": -1,
        "last_check": datetime.now().isoformat()
    }
    
    speed = test_api_speed(api_config)
    if speed > 0:
        result["alive"] = True
        result["speed"] = speed
    
    return result


def update_all_health(progress_callback=None) -> Dict:
    """更新所有接口的健康状态"""
    results = {}
    total = len([api for api in API_LIST if api.get("enabled", True)])
    
    for i, api in enumerate(API_LIST):
        if not api.get("enabled", True):
            continue
        
        if progress_callback:
            progress_callback(i + 1, total, api["name"])
        
        result = check_api_health(api)
        results[api["name"]] = result
    
    save_health_records(results)
    return results


def need_health_check() -> bool:
    """判断是否需要健康检查"""
    if not HEALTH_CHECK_ENABLED:
        return False
    
    records = load_health_records()
    if not records:
        return True
    
    last_check = None
    for r in records.values():
        if "last_check" in r:
            try:
                check_time = datetime.fromisoformat(r["last_check"])
                if last_check is None or check_time > last_check:
                    last_check = check_time
            except:
                pass
    
    if last_check is None:
        return True
    
    hours_passed = (datetime.now() - last_check).total_seconds() / 3600
    return hours_passed >= HEALTH_CHECK_INTERVAL


def apply_health_to_api_list(api_list: List[Dict]) -> List[Dict]:
    """根据健康记录更新接口列表的 enabled 状态"""
    if not HEALTH_CHECK_AUTO_DISABLE:
        return api_list
    
    records = load_health_records()
    if not records:
        return api_list
    
    for api in api_list:
        name = api.get("name")
        if name in records:
            record = records[name]
            if not record.get("alive", False):
                if api.get("enabled", True):
                    print(f"  [健康] 接口 {name} 已失效，自动禁用")
                    api["enabled"] = False
    
    return api_list


# ==================== 历史记录 ====================

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "play_history.json")
MAX_HISTORY = 20


def load_history() -> List[Dict]:
    """加载历史记录"""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history: List[Dict]):
    """保存历史记录"""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存历史记录失败: {e}")


def add_to_history(video_name: str, episode_name: str, url: str, source: str):
    """添加播放记录"""
    history = load_history()
    record = {
        "video_name": video_name,
        "episode_name": episode_name,
        "url": url,
        "source": source,
        "last_play": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    history = [h for h in history if h.get("video_name") != video_name]
    history.insert(0, record)
    if len(history) > MAX_HISTORY:
        history = history[:MAX_HISTORY]
    save_history(history)


def clear_history():
    """清空历史记录"""
    save_history([])


# ==================== 网络请求 ====================

def http_get(url: str, params: Dict = None, headers: Dict = None) -> Optional[str]:
    """发送GET请求"""
    default_headers = {'User-Agent': USER_AGENT}
    if headers:
        default_headers.update(headers)
    try:
        response = requests.get(url, params=params, headers=default_headers, timeout=REQUEST_TIMEOUT)
        response.encoding = 'utf-8'
        return response.text
    except requests.RequestException as e:
        print(f"  [网络错误] {e}")
        return None


# ==================== 解析模块 ====================

def build_api_url(api_config: Dict) -> str:
    """构建API URL"""
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


def extract_episodes_from_string(text: str) -> List[Dict]:
    """从字符串提取剧集列表"""
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


def detect_format(text: str) -> str:
    """检测数据格式"""
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


def parse_xml_videos(xml_text: str, source_name: str) -> List[Dict]:
    """解析XML格式"""
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
        print(f"  [解析错误] {e}")
    return videos


def parse_json_videos(json_text: str, source_name: str) -> List[Dict]:
    """解析JSON格式"""
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
        print(f"  [解析错误] {e}")
    return videos


def get_categories_from_api(api_config: Dict) -> List[Dict]:
    """从接口获取分类列表"""
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
                    categories.append({
                        "id": type_id.text,
                        "name": type_name.text
                    })
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


# ==================== 搜索模块 ====================

def search_single_api(api_config: Dict, keyword: str, category_id: str = None) -> List[Dict]:
    """单个接口搜索（支持分类筛选）"""
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
        
        print(f"  [搜索] {source_name}...")
        response_text = http_get(url, params=params)
        if not response_text:
            return []
        
        fmt = detect_format(response_text)
        if fmt == 'xml':
            parsed = parse_xml_videos(response_text, source_name)
        elif fmt == 'json':
            parsed = parse_json_videos(response_text, source_name)
        else:
            print(f"  [警告] {source_name} 返回格式未知")
            return []
        
        for item in parsed:
            episodes = item.get('episodes', [])
            name = item.get('name', '')
            if episodes and name:
                if not api_config.get("searchable", True):
                    if keyword.lower() not in name.lower():
                        continue
                videos.append({"name": name, "episodes": episodes, "source": source_name})
        
        if videos:
            print(f"  [找到] {source_name} 找到 {len(videos)} 个结果")
        else:
            print(f"  [无果] {source_name} 未找到匹配")
        return videos
    except Exception as e:
        print(f"  [错误] {source_name} 搜索失败: {e}")
        return []


def search_with_apis(apis: List[Dict], keyword: str, category_id: str = None) -> List[Dict]:
    """使用指定的接口列表搜索"""
    all_results = []
    
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = {executor.submit(search_single_api, api, keyword, category_id): api for api in apis}
        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                pass
    
    seen = set()
    unique = []
    for r in all_results:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique


# ==================== 播放模块 ====================

def play_with_mpv(video: Dict) -> bool:
    """调用mpv播放"""
    if not video:
        return False
    
    url = video.get("url")
    name = video.get("name", "未知影片")
    
    if not url:
        print("❌ 播放地址为空")
        return False
    
    print(f"🎬 正在播放: {name}")
    print(f"📡 地址: {url[:80]}..." if len(url) > 80 else f"📡 地址: {url}")
    
    play_url = url
    if ENABLE_AD_FILTER and url.endswith('.m3u8'):
        try:
            play_url = get_cleaned_m3u8(url)
            print(f"  [广告过滤] 已启用")
        except Exception as e:
            print(f"  [广告过滤] 失败: {e}")
    
    cmd = [MPV_PATH, play_url, f"--title={name}"]
    
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
            )
        else:
            subprocess.Popen(cmd, start_new_session=True)
        
        print(f"  [成功] mpv 已启动")
        
        parts = name.split(" - ", 1)
        video_name = parts[0]
        episode_name = parts[1] if len(parts) > 1 else "正片"
        add_to_history(video_name, episode_name, url, video.get('source', '未知'))
        
        return True
    except Exception as e:
        print(f"❌ 播放失败: {e}")
        return False


def get_cleaned_m3u8(original_url: str) -> str:
    """清洗 m3u8（简化版）"""
    return original_url


# ==================== GUI 界面 ====================

class VideoSearchGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("影视搜索工具 v1.0")
        self.root.geometry("1150x850")
        self.root.minsize(1050, 750)
        
        self.current_results = []
        self.current_episodes = []
        self.current_video_name = ""
        self.api_speeds = {}
        self.categories = []
        
        # 分页相关
        self.current_page = 1
        self.total_pages = 1
        self.current_api_config = None
        self.current_category_id = None
        self.current_category_name = None
        
        self.check_health_on_startup()
        
        self.setup_ui()
        self.update_group_list()
        self.update_api_list()
        
    def check_health_on_startup(self):
        """启动时检查接口健康"""
        if not HEALTH_CHECK_ENABLED:
            return
        
        if not need_health_check():
            records = load_health_records()
            for api in API_LIST:
                name = api.get("name")
                if name in records:
                    self.api_speeds[name] = records[name].get("speed", -1)
            return
        
        def do_health_check():
            print("\n[健康检查] 正在检测接口状态...")
            
            def update_progress(current, total, name):
                print(f"  [健康检查] {current}/{total}: {name}")
            
            results = update_all_health(update_progress)
            
            for name, result in results.items():
                self.api_speeds[name] = result.get("speed", -1)
            
            if HEALTH_CHECK_AUTO_DISABLE:
                apply_health_to_api_list(API_LIST)
                self.root.after(0, self.update_api_list)
                self.root.after(0, self.update_group_list)
            
            print(f"[健康检查] 完成，共检查 {len(results)} 个接口\n")
        
        threading.Thread(target=do_health_check, daemon=True).start()
    
    def setup_ui(self):
        # 顶部搜索区域
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        
        ttk.Label(top_frame, text="关键词:").pack(side=tk.LEFT)
        self.entry = ttk.Entry(top_frame, width=30, font=("Arial", 12))
        self.entry.pack(side=tk.LEFT, padx=5)
        self.entry.bind("<Return>", lambda e: self.search())
        
        # 搜索模式选择
        self.search_mode = ttk.Combobox(
            top_frame,
            values=["🔍 聚合搜索", "📡 单接口", "📁 组内搜索"],
            width=12,
            state="readonly"
        )
        self.search_mode.current(0)
        self.search_mode.pack(side=tk.LEFT, padx=5)
        self.search_mode.bind("<<ComboboxSelected>>", self.on_mode_changed)
        
        # 分组选择
        self.group_combo = ttk.Combobox(top_frame, width=12, state="readonly")
        self.group_combo.pack(side=tk.LEFT, padx=5)
        
        # 单接口选择
        self.api_combo = ttk.Combobox(top_frame, width=15, state="readonly")
        self.api_combo.pack(side=tk.LEFT, padx=5)
        
        # 分类选择
        self.category_combo = ttk.Combobox(top_frame, width=12, state="readonly")
        self.category_combo.pack(side=tk.LEFT, padx=5)
        
        # 浏览按钮
        self.browse_btn = ttk.Button(top_frame, text="浏览", command=self.browse_category)
        self.browse_btn.pack(side=tk.LEFT, padx=5)
        
        # 测速按钮
        self.speed_btn = ttk.Button(top_frame, text="⏱️ 测速", command=self.test_speed)
        self.speed_btn.pack(side=tk.LEFT, padx=5)
        
        # 健康检查按钮
        self.health_btn = ttk.Button(top_frame, text="🏥 健康检查", command=self.manual_health_check)
        self.health_btn.pack(side=tk.LEFT, padx=5)
        
        # 搜索按钮
        self.btn = ttk.Button(top_frame, text="搜索", command=self.search)
        self.btn.pack(side=tk.LEFT, padx=5)
        
        # 初始隐藏
        self.group_combo.pack_forget()
        self.api_combo.pack_forget()
        self.category_combo.pack_forget()
        
        # 搜索结果
        result_frame = ttk.LabelFrame(self.root, text="搜索结果 (双击加载剧集 | 点击列标题排序)", padding="5")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        columns = ("序号", "名称", "集数", "来源", "速度", "播放地址")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=12)
        
        self.tree.heading("序号", text="序号", command=lambda: self.sort_by_column("序号", False))
        self.tree.column("序号", width=45, anchor="center")
        
        self.tree.heading("名称", text="名称", command=lambda: self.sort_by_column("名称", False))
        self.tree.column("名称", width=250)
        
        self.tree.heading("集数", text="集数", command=lambda: self.sort_by_column("集数", False))
        self.tree.column("集数", width=55, anchor="center")
        
        self.tree.heading("来源", text="来源", command=lambda: self.sort_by_column("来源", False))
        self.tree.column("来源", width=100)
        
        self.tree.heading("速度", text="速度(ms)", command=lambda: self.sort_by_column("速度", True))
        self.tree.column("速度", width=65, anchor="center")
        
        self.tree.heading("播放地址", text="播放地址", command=lambda: self.sort_by_column("播放地址", False))
        self.tree.column("播放地址", width=480)
        
        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", self.on_select)
        
        # 底部区域
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 剧集列表
        episode_frame = ttk.LabelFrame(bottom_frame, text="剧集列表 (双击播放)", padding="5")
        episode_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.episode_listbox = tk.Listbox(episode_frame, height=10, font=("Arial", 10))
        self.episode_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ep_scrollbar = ttk.Scrollbar(episode_frame, orient=tk.VERTICAL, command=self.episode_listbox.yview)
        self.episode_listbox.configure(yscrollcommand=ep_scrollbar.set)
        ep_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.episode_listbox.bind("<Double-1>", self.play)
        
        # 按钮区
        btn_frame = ttk.Frame(bottom_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        
        ttk.Button(btn_frame, text="▶ 播放选中剧集", command=self.play, width=18).pack(pady=5)
        ttk.Button(btn_frame, text="🎬 连播模式", command=self.start_auto_play, width=18).pack(pady=5)
        ttk.Button(btn_frame, text="📁 导出播放列表", command=self.export_playlist, width=18).pack(pady=5)
        ttk.Button(btn_frame, text="📜 播放历史", command=self.show_history, width=18).pack(pady=5)
        ttk.Button(btn_frame, text="🗑 清空历史", command=self.clear_history, width=18).pack(pady=5)
        
        # 分页控件（初始不显示）
        self.pagination_frame = ttk.Frame(self.root)
        # 不pack，等浏览时再显示
        
        # 状态栏
        self.status = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, pady=(5, 0))
    
    def sort_by_column(self, col, is_numeric=False):
        """按列排序"""
        items = [(self.tree.set(item, col), item) for item in self.tree.get_children('')]
        
        if not items:
            return
        
        if is_numeric:
            def get_num_value(val):
                if val == "未测":
                    return 999999
                elif val == "超时":
                    return 999998
                else:
                    try:
                        return int(val)
                    except:
                        return 999997
            items.sort(key=lambda x: get_num_value(x[0]))
        else:
            items.sort(key=lambda x: x[0].lower())
        
        for index, (_, item) in enumerate(items):
            self.tree.move(item, '', index)
        
        for col_name in ["序号", "名称", "集数", "来源", "速度", "播放地址"]:
            self.tree.heading(col_name, text=col_name)
        self.tree.heading(col, text=f"{col} ▼")
    
    def test_speed(self):
        """手动测速"""
        self.update_status("正在测速...")
        self.speed_btn.config(state=tk.DISABLED)
        
        def do_test():
            results = {}
            total = len([api for api in API_LIST if api.get("enabled", True)])
            
            for i, api in enumerate(API_LIST):
                if not api.get("enabled", True):
                    continue
                
                self.root.after(0, lambda c=i+1, t=total, n=api["name"]: 
                    self.update_status(f"测速中: {c}/{t} - {n}"))
                
                speed = test_api_speed(api)
                results[api["name"]] = speed
                self.api_speeds[api["name"]] = speed
                
                if speed > 0:
                    print(f"  [测速] {api['name']}: {speed*1000:.0f}ms")
                else:
                    print(f"  [测速] {api['name']}: 超时/失败")
            
            records = load_health_records()
            for name, speed in results.items():
                if name not in records:
                    records[name] = {}
                records[name]["speed"] = speed
                records[name]["last_check"] = datetime.now().isoformat()
                records[name]["alive"] = speed > 0
            save_health_records(records)
            
            self.root.after(0, lambda: self.update_status(f"测速完成"))
            self.root.after(0, lambda: self.speed_btn.config(state=tk.NORMAL))
            self.root.after(0, messagebox.showinfo, "测速完成", "测速已完成，可在搜索结果中查看接口速度")
        
        threading.Thread(target=do_test, daemon=True).start()
    
    def manual_health_check(self):
        """手动健康检查"""
        self.update_status("正在健康检查...")
        self.health_btn.config(state=tk.DISABLED)
        
        def do_check():
            def update_progress(current, total, name):
                self.root.after(0, lambda: self.update_status(f"健康检查: {current}/{total} - {name}"))
            
            results = update_all_health(update_progress)
            
            for name, result in results.items():
                self.api_speeds[name] = result.get("speed", -1)
            
            if HEALTH_CHECK_AUTO_DISABLE:
                apply_health_to_api_list(API_LIST)
                self.root.after(0, self.update_api_list)
                self.root.after(0, self.update_group_list)
            
            alive_count = sum(1 for r in results.values() if r.get("alive"))
            dead_count = len(results) - alive_count
            
            self.root.after(0, lambda: self.update_status(f"健康检查完成: {alive_count} 正常, {dead_count} 失效"))
            self.root.after(0, lambda: self.health_btn.config(state=tk.NORMAL))
            self.root.after(0, messagebox.showinfo, "健康检查", 
                f"检查完成\n正常接口: {alive_count}\n失效接口: {dead_count}\n\n失效接口已被自动禁用")
        
        threading.Thread(target=do_check, daemon=True).start()
    
    def get_speed_display(self, source_name: str) -> str:
        """获取速度显示文本"""
        speed = self.api_speeds.get(source_name, -1)
        if speed > 0:
            return f"{speed*1000:.0f}"
        elif speed == -1:
            return "未测"
        else:
            return "超时"
    
    def update_group_list(self):
        """更新分组列表"""
        groups = set()
        for api in API_LIST:
            if api.get("enabled", True):
                group = api.get("group", "未分组")
                groups.add(group)
        groups = sorted(list(groups))
        self.group_combo['values'] = groups
        if groups:
            self.group_combo.current(0)
    
    def update_api_list(self):
        """更新单接口列表"""
        names = [api["name"] for api in API_LIST if api.get("enabled", True)]
        self.api_combo['values'] = names
        if names:
            self.api_combo.current(0)
    
    def on_mode_changed(self, event=None):
        """模式切换时显示/隐藏对应的下拉框"""
        mode = self.search_mode.get()
        
        # 清除分页控件
        if hasattr(self, 'pagination_frame'):
            self.pagination_frame.pack_forget()
        
        self.group_combo.pack_forget()
        self.api_combo.pack_forget()
        self.category_combo.pack_forget()
        
        if mode == "📡 单接口":
            self.api_combo.pack(side=tk.LEFT, padx=5)
            self.category_combo.pack(side=tk.LEFT, padx=5)
            self.api_combo.bind("<<ComboboxSelected>>", self.on_api_selected)
        elif mode == "📁 组内搜索":
            self.group_combo.pack(side=tk.LEFT, padx=5)
    
    def on_api_selected(self, event=None):
        """选中接口后，加载该接口的分类列表"""
        api_name = self.api_combo.get()
        if not api_name:
            return
        
        api_config = None
        for api in API_LIST:
            if api.get("name") == api_name:
                api_config = api
                break
        
        if not api_config:
            return
        
        self.update_status(f"正在获取分类列表: {api_name}")
        self.category_combo.config(values=["全部"])
        self.category_combo.current(0)
        
        def fetch_categories():
            categories = get_categories_from_api(api_config)
            self.root.after(0, lambda: self.update_category_list(categories))
        
        threading.Thread(target=fetch_categories, daemon=True).start()
    
    def update_category_list(self, categories: List[Dict]):
        """更新分类下拉框"""
        self.categories = categories
        names = ["全部"] + [c["name"] for c in categories]
        self.category_combo['values'] = names
        self.category_combo.current(0)
        self.update_status(f"已加载 {len(categories)} 个分类")
    
    def browse_category(self):
        """浏览选中分类的内容（支持分页）"""
        mode = self.search_mode.get()
        
        if mode != "📡 单接口":
            messagebox.showinfo("提示", "请先选择「单接口」模式")
            return
        
        api_name = self.api_combo.get()
        if not api_name:
            messagebox.showinfo("提示", "请先选择一个接口")
            return
        
        category = self.category_combo.get()
        if not category or category == "全部":
            messagebox.showinfo("提示", "请先选择一个分类")
            return
        
        category_id = None
        for c in self.categories:
            if c["name"] == category:
                category_id = c["id"]
                break
        
        if not category_id:
            messagebox.showinfo("提示", "无法获取分类ID")
            return
        
        # 保存当前浏览状态
        self.current_api_config = None
        for api in API_LIST:
            if api.get("name") == api_name:
                self.current_api_config = api
                break
        
        self.current_category_id = category_id
        self.current_category_name = category
        self.current_page = 1
        
        # 清空列表
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.episode_listbox.delete(0, tk.END)
        
        self.load_browse_page()
    
    def load_browse_page(self):
        """加载当前页的浏览内容"""
        if not self.current_api_config:
            return
        
        self.update_status(f"正在浏览: {self.current_api_config['name']} - {self.current_category_name} - 第{self.current_page}页")
        self.browse_btn.config(state=tk.DISABLED)
        
        def do_load():
            url = build_api_url(self.current_api_config)
            params = {"ac": "videolist", "pg": self.current_page, "pagesize": 30, "t": self.current_category_id}
            
            try:
                response_text = http_get(url, params=params)
                if not response_text:
                    self.root.after(0, lambda: self.update_status("获取分类内容失败"))
                    return
                
                fmt = detect_format(response_text)
                if fmt == 'xml':
                    videos = parse_xml_videos(response_text, self.current_api_config["name"])
                    # 获取总页数
                    import xml.etree.ElementTree as ET
                    try:
                        root = ET.fromstring(response_text)
                        list_node = root.find('list')
                        if list_node is not None:
                            pagecount = list_node.get('pagecount')
                            if pagecount:
                                self.root.after(0, lambda: setattr(self, 'total_pages', int(pagecount)))
                    except:
                        pass
                elif fmt == 'json':
                    videos = parse_json_videos(response_text, self.current_api_config["name"])
                    try:
                        data = json.loads(response_text)
                        pagecount = data.get('pagecount', data.get('total_pages', 1))
                        if pagecount:
                            self.root.after(0, lambda: setattr(self, 'total_pages', int(pagecount)))
                    except:
                        pass
                else:
                    self.root.after(0, lambda: self.update_status("返回格式未知"))
                    return
                
                self.root.after(0, lambda: self.on_browse_results(videos))
                self.root.after(0, lambda: self.update_pagination_ui())
            except Exception as e:
                print(f"浏览失败: {e}")
                self.root.after(0, lambda: self.update_status(f"浏览失败: {e}"))
            finally:
                self.root.after(0, lambda: self.browse_btn.config(state=tk.NORMAL))
        
        threading.Thread(target=do_load, daemon=True).start()
    
    def update_pagination_ui(self):
        """更新分页UI"""
        # 显示分页控件
        self.pagination_frame.pack(fill=tk.X, pady=(0, 5), before=self.status)
        
        # 清除旧控件
        for widget in self.pagination_frame.winfo_children():
            widget.destroy()
        
        self.prev_btn = ttk.Button(self.pagination_frame, text="◀ 上一页", command=self.prev_page)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        
        self.page_label = ttk.Label(self.pagination_frame, text=f"第 {self.current_page} / {self.total_pages} 页")
        self.page_label.pack(side=tk.LEFT, padx=10)
        
        self.next_btn = ttk.Button(self.pagination_frame, text="下一页 ▶", command=self.next_page)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        
        self.page_entry = ttk.Entry(self.pagination_frame, width=6)
        self.page_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.pagination_frame, text="跳转", command=self.jump_to_page).pack(side=tk.LEFT, padx=2)
        
        # 更新按钮状态
        if self.current_page <= 1:
            self.prev_btn.config(state=tk.DISABLED)
        else:
            self.prev_btn.config(state=tk.NORMAL)
        
        if self.current_page >= self.total_pages:
            self.next_btn.config(state=tk.DISABLED)
        else:
            self.next_btn.config(state=tk.NORMAL)
    
    def prev_page(self):
        """上一页"""
        if self.current_page > 1:
            self.current_page -= 1
            self.load_browse_page()
    
    def next_page(self):
        """下一页"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.load_browse_page()
    
    def jump_to_page(self):
        """跳转到指定页"""
        try:
            page = int(self.page_entry.get())
            if 1 <= page <= self.total_pages:
                self.current_page = page
                self.load_browse_page()
            else:
                messagebox.showinfo("提示", f"页码范围 1-{self.total_pages}")
        except ValueError:
            messagebox.showinfo("提示", "请输入有效数字")
    
    def on_browse_results(self, results):
        """显示浏览结果"""
        self.current_results = results
        
        # 清空列表
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        if not results:
            self.update_status("该分类下没有找到内容")
            return
        
        for idx, v in enumerate(results, 1):
            name = v['name'][:42] if len(v['name']) > 42 else v['name']
            ep_count = len(v.get('episodes', []))
            ep_text = f"{ep_count}集" if ep_count > 0 else "无"
            source = v['source']
            speed_display = self.get_speed_display(source)
            first_url = v.get('episodes', [{}])[0].get('url', '无') if v.get('episodes') else '无'
            self.tree.insert("", tk.END, values=(idx, name, ep_text, source, speed_display, self.truncate_url(first_url, 60)))
        
        self.update_status(f"第 {self.current_page} 页，共 {len(results)} 条记录")
    
    def get_search_apis(self):
        """根据当前模式获取要搜索的接口列表"""
        mode = self.search_mode.get()
        
        if mode == "📡 单接口":
            selected = self.api_combo.get()
            apis = [api for api in API_LIST if api.get("name") == selected and api.get("enabled", True)]
            
            category = self.category_combo.get()
            category_id = None
            if category and category != "全部":
                for c in self.categories:
                    if c["name"] == category:
                        category_id = c["id"]
                        break
            return apis, category_id
        elif mode == "📁 组内搜索":
            selected_group = self.group_combo.get()
            return [api for api in API_LIST if api.get("group") == selected_group and api.get("enabled", True)], None
        else:
            return [api for api in API_LIST if api.get("enabled", True)], None
    
    def truncate_url(self, url, max_len=60):
        if len(url) <= max_len:
            return url
        return url[:max_len-3] + "..."
    
    def update_status(self, msg):
        self.status.config(text=msg)
        self.root.update_idletasks()
    
    def search(self):
        keyword = self.entry.get().strip()
        if not keyword:
            self.update_status("请输入搜索关键词")
            return
        
        # 清除分页控件
        self.pagination_frame.pack_forget()
        
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.episode_listbox.delete(0, tk.END)
        self.current_results = []
        self.current_episodes = []
        
        apis, category_id = self.get_search_apis()
        mode = self.search_mode.get()
        
        if not apis:
            self.update_status("没有可用的接口")
            return
        
        self.update_status(f"正在搜索: {keyword} ({mode})")
        self.btn.config(state=tk.DISABLED)
        
        def do_search():
            results = search_with_apis(apis, keyword, category_id)
            self.root.after(0, lambda: self.on_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def on_results(self, results):
        self.current_results = results
        self.btn.config(state=tk.NORMAL)
        
        if not results:
            self.update_status("没有找到匹配的视频")
            return
        
        for idx, v in enumerate(results, 1):
            name = v['name'][:42] if len(v['name']) > 42 else v['name']
            ep_count = len(v.get('episodes', []))
            ep_text = f"{ep_count}集" if ep_count > 0 else "无"
            source = v['source']
            speed_display = self.get_speed_display(source)
            first_url = v.get('episodes', [{}])[0].get('url', '无') if v.get('episodes') else '无'
            self.tree.insert("", tk.END, values=(idx, name, ep_text, source, speed_display, self.truncate_url(first_url, 60)))
        
        self.update_status(f"找到 {len(results)} 个结果")
    
    def on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        
        item = self.tree.item(selection[0])
        idx = int(item['values'][0]) - 1
        
        if 0 <= idx < len(self.current_results):
            video = self.current_results[idx]
            self.current_video_name = video['name']
            self.current_episodes = video.get('episodes', [])
            
            self.episode_listbox.delete(0, tk.END)
            for ep in self.current_episodes:
                short_url = self.truncate_url(ep['url'], 45)
                self.episode_listbox.insert(tk.END, f"{ep['name']} - {short_url}")
            
            self.update_status(f"已加载《{video['name']}》，共 {len(self.current_episodes)} 集")
    
    def play(self, event=None):
        if not self.current_episodes:
            self.update_status("请先选择视频")
            return
        
        selection = self.episode_listbox.curselection()
        if not selection:
            self.update_status("请选择剧集")
            return
        
        idx = selection[0]
        episode = self.current_episodes[idx]
        
        full_name = f"{self.current_video_name} - {episode['name']}"
        self.update_status(f"正在播放: {full_name}")
        
        threading.Thread(target=lambda: play_with_mpv({"name": full_name, "url": episode['url']}), daemon=True).start()
    
    def start_auto_play(self):
        if not self.current_episodes:
            self.update_status("请先选择视频")
            return
        
        selection = self.episode_listbox.curselection()
        start_idx = selection[0] if selection else 0
        
        self.update_status(f"连播模式已启动，从第{start_idx+1}集开始")
        
        def play_sequence(idx):
            if idx >= len(self.current_episodes):
                self.update_status("连播结束")
                return
            episode = self.current_episodes[idx]
            play_with_mpv({"name": f"{self.current_video_name} - {episode['name']}", "url": episode['url']})
            if idx + 1 < len(self.current_episodes):
                self.update_status(f"第{idx+1}集播放中，下一集是第{idx+2}集")
        
        threading.Thread(target=lambda: play_sequence(start_idx), daemon=True).start()
    
    def export_playlist(self):
        if not self.current_episodes:
            self.update_status("请先选择视频")
            return
        
        output_dir = os.path.join(os.path.dirname(__file__), "playlists")
        os.makedirs(output_dir, exist_ok=True)
        
        safe_name = "".join(c for c in self.current_video_name if c.isalnum() or c in ' ._-')
        filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.m3u"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write(f"# 播放列表: {self.current_video_name}\n")
            f.write(f"# 总集数: {len(self.current_episodes)}\n\n")
            for ep in self.current_episodes:
                f.write(f"#EXTINF:0,{self.current_video_name} - {ep['name']}\n")
                f.write(f"{ep['url']}\n")
        
        self.update_status(f"已导出: {filepath}")
        messagebox.showinfo("导出成功", f"播放列表已保存到:\n{filepath}")
    
    def show_history(self):
        """显示播放历史（支持删除选中）"""
        history = load_history()
        if not history:
            self.update_status("暂无播放历史")
            messagebox.showinfo("提示", "暂无播放历史")
            return
        
        win = tk.Toplevel(self.root)
        win.title("播放历史")
        win.geometry("650x500")
        win.minsize(550, 400)
        
        frame = ttk.Frame(win, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        lb = tk.Listbox(list_frame, font=("Arial", 10), yscrollcommand=scrollbar.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=lb.yview)
        
        history_data = []
        for r in history:
            name = r.get('video_name', '未知')
            ep = r.get('episode_name', '正片')
            time = r.get('last_play', '')[:16]
            display = f"{name} - {ep}"
            if time:
                display += f"  ({time})"
            lb.insert(tk.END, display)
            history_data.append(r)
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        def play_selected():
            sel = lb.curselection()
            if sel:
                r = history_data[sel[0]]
                threading.Thread(target=lambda: play_with_mpv({
                    "name": f"{r['video_name']} - {r['episode_name']}",
                    "url": r['url']
                }), daemon=True).start()
                win.destroy()
        
        def delete_selected():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("提示", "请先选中要删除的记录")
                return
            
            r = history_data[sel[0]]
            result = messagebox.askyesno("确认删除", f"确定要删除《{r['video_name']} - {r['episode_name']}》吗？")
            if not result:
                return
            
            del history_data[sel[0]]
            lb.delete(sel[0])
            
            new_history = []
            for item in history_data:
                new_history.append({
                    "video_name": item.get('video_name'),
                    "episode_name": item.get('episode_name'),
                    "url": item.get('url'),
                    "source": item.get('source'),
                    "last_play": item.get('last_play')
                })
            save_history(new_history)
            self.update_status("已删除选中的历史记录")
            
            if not history_data:
                messagebox.showinfo("提示", "历史记录已清空")
                win.destroy()
        
        def clear_all():
            result = messagebox.askyesno("确认清空", "确定要清空所有播放历史吗？")
            if result:
                clear_history()
                win.destroy()
                self.update_status("历史记录已清空")
        
        ttk.Button(btn_frame, text="▶ 播放选中", command=play_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑 删除选中", command=delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑 清空全部", command=clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="关闭", command=win.destroy).pack(side=tk.RIGHT, padx=5)
    
    def clear_history(self):
        if messagebox.askyesno("确认", "确定要清空所有播放历史吗？"):
            clear_history()
            self.update_status("历史记录已清空")
    
    def run(self):
        self.root.mainloop()


def main():
    if not API_LIST:
        print("警告: config.json 中没有配置任何接口")
    app = VideoSearchGUI()
    app.run()


if __name__ == "__main__":
    main()