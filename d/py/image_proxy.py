#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote, unquote
import json
import re
from threading import Lock
import time

class WaterfallImageHandler(BaseHTTPRequestHandler):
    base_url = "https://desk.tooopen.com/"
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    # 分类配置
    categories = {
        'model': '美女明星',
        'beauty': '清纯美女',
        'meinv': '性感美女',
        'artphoto': '艺术写真', 
        't_ribenmeinv':'日本美女', 
        'oumeimeinv': '欧美美女'
    }
    
    # 简单缓存，避免重复请求同一页（可选）
    cache = {}
    cache_lock = Lock()
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/' or path == '/index.html':
            self.serve_index()
        elif path.startswith('/image/'):
            self.proxy_image(path[7:])
        elif path.startswith('/api/list/'):
            self.serve_list_api(path[10:])
        else:
            self.send_error(404, "Not Found")
    
    def serve_index(self):
        """瀑布流 + 无限滚动页面"""
        html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>美图公社 - 瀑布流浏览</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #0f0f0f;
            min-height: 100vh;
        }
        
        /* 头部 */
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 30px 20px;
            text-align: center;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        
        .header h1 {
            font-size: 1.8em;
            margin-bottom: 8px;
            letter-spacing: 2px;
        }
        
        .header p {
            opacity: 0.7;
            font-size: 0.9em;
        }
        
        /* 分类导航 - 横向滚动 */
        .category-nav {
            position: sticky;
            top: 100px;
            z-index: 99;
            background: rgba(15,15,15,0.95);
            backdrop-filter: blur(10px);
            padding: 12px 20px;
            display: flex;
            gap: 12px;
            overflow-x: auto;
            scrollbar-width: thin;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .category-nav::-webkit-scrollbar {
            height: 3px;
        }
        
        .category-btn {
            padding: 8px 20px;
            border: none;
            border-radius: 30px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            background: rgba(255,255,255,0.1);
            color: #ddd;
            transition: all 0.3s ease;
            white-space: nowrap;
            flex-shrink: 0;
        }
        
        .category-btn:hover {
            background: rgba(255,255,255,0.2);
            transform: scale(1.02);
        }
        
        .category-btn.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            box-shadow: 0 4px 12px rgba(102,126,234,0.4);
        }
        
        /* 瀑布流容器 */
        .waterfall {
            column-count: 4;
            column-gap: 16px;
            padding: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }
        
        /* 图片卡片 */
        .image-card {
            break-inside: avoid;
            margin-bottom: 16px;
            background: #1a1a1a;
            border-radius: 12px;
            overflow: hidden;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
        }
        
        .image-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 28px rgba(0,0,0,0.3);
        }
        
        .image-card img {
            width: 100%;
            display: block;
            transition: transform 0.3s ease;
        }
        
        .image-card:hover img {
            transform: scale(1.02);
        }
        
        /* 图片信息浮层 */
        .image-overlay {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            background: linear-gradient(transparent, rgba(0,0,0,0.8));
            padding: 12px;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .image-card:hover .image-overlay {
            opacity: 1;
        }
        
        .image-title {
            color: white;
            font-size: 12px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        /* 加载动画 */
        .loading-container {
            text-align: center;
            padding: 40px;
            clear: both;
        }
        
        .loader {
            display: inline-block;
            width: 40px;
            height: 40px;
            border: 3px solid rgba(255,255,255,0.2);
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .loading-text {
            color: #888;
            margin-top: 12px;
            font-size: 14px;
        }
        
        /* 弹窗 - 优雅放大 */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            backdrop-filter: blur(8px);
        }
        
        .modal.active {
            display: flex;
        }
        
        .modal-content {
            max-width: 90vw;
            max-height: 90vh;
            position: relative;
        }
        
        .modal img {
            max-width: 100%;
            max-height: 90vh;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        }
        
        .modal-close {
            position: absolute;
            top: -40px;
            right: 0;
            color: white;
            font-size: 30px;
            cursor: pointer;
            background: rgba(0,0,0,0.5);
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }
        
        .modal-close:hover {
            background: rgba(255,255,255,0.2);
            transform: scale(1.1);
        }
        
        /* 回到顶部按钮 */
        .back-to-top {
            position: fixed;
            bottom: 30px;
            right: 30px;
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s;
            z-index: 99;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        
        .back-to-top.show {
            opacity: 1;
            visibility: visible;
        }
        
        .back-to-top:hover {
            transform: scale(1.1);
        }
        
        .back-to-top svg {
            width: 24px;
            height: 24px;
            fill: white;
        }
        
        /* 响应式列数 */
        @media (max-width: 1200px) {
            .waterfall { column-count: 3; }
        }
        @media (max-width: 800px) {
            .waterfall { column-count: 2; }
            .header h1 { font-size: 1.4em; }
            .category-nav { top: 85px; }
        }
        @media (max-width: 500px) {
            .waterfall { column-count: 1; }
        }
        
        /* 空状态 */
        .empty-state {
            text-align: center;
            padding: 80px 20px;
            color: #666;
        }
        
        /* 页脚 */
        .footer {
            text-align: center;
            padding: 30px;
            color: #555;
            font-size: 12px;
            border-top: 1px solid rgba(255,255,255,0.05);
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🖼️ 美图公社 · 瀑布流</h1>
        <p>无限滚动 | 点击放大 | 实时浏览</p>
    </div>
    
    <div class="category-nav" id="categoryNav"></div>
    
    <div class="waterfall" id="waterfall"></div>
    
    <div class="loading-container" id="loadingContainer">
        <div class="loader"></div>
        <div class="loading-text">加载中...</div>
    </div>
    
    <div class="footer" id="footer"></div>
    
    <div class="modal" id="modal" onclick="closeModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <div class="modal-close" onclick="closeModal()">✕</div>
            <img id="modalImg" src="">
        </div>
    </div>
    
    <div class="back-to-top" id="backToTop" onclick="scrollToTop()">
        <svg viewBox="0 0 24 24"><path d="M12 4l-8 8h6v8h4v-8h6z"/></svg>
    </div>

    <script>
        let currentCategory = 'model';
        let currentPage = 1;
        let isLoading = false;
        let hasMore = true;
        let observer = null;
        
        const categories = {
            'model': '美女明星',
            'beauty': '清纯美女', 
            'meinv': '性感美女',
            'artphoto': '艺术写真', 
            't_ribenmeinv':'日本美女', 
            'oumeimeinv': '欧美美女'
        };
        
        // 构建分类导航
        function buildNav() {
            const nav = document.getElementById('categoryNav');
            nav.innerHTML = Object.entries(categories).map(([key, name]) => 
                `<button class="category-btn ${key === currentCategory ? 'active' : ''}" onclick="switchCategory('${key}')">${name}</button>`
            ).join('');
        }
        
        // 切换分类
        function switchCategory(cat) {
            if (cat === currentCategory) return;
            currentCategory = cat;
            currentPage = 1;
            hasMore = true;
            
            // 清空瀑布流
            document.getElementById('waterfall').innerHTML = '';
            
            // 更新激活样式
            document.querySelectorAll('.category-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.textContent === categories[cat]) {
                    btn.classList.add('active');
                }
            });
            
            // 重新加载
            loadMoreImages();
        }
        
        // 加载图片
        async function loadMoreImages() {
            if (isLoading || !hasMore) return;
            
            isLoading = true;
            document.getElementById('loadingContainer').style.display = 'block';
            
            try {
                const resp = await fetch(`/api/list/${currentCategory}?page=${currentPage}`);
                const data = await resp.json();
                
                if (data.images && data.images.length > 0) {
                    appendImages(data.images);
                    currentPage++;
                    hasMore = data.hasNext;
                    
                    if (!hasMore) {
                        document.getElementById('loadingContainer').innerHTML = '<div class="loading-text">✨ 已经到底啦 ✨</div>';
                        document.getElementById('footer').innerHTML = '© 图片实时来自 desk.tooopen.com | 本地瀑布流浏览';
                    } else {
                        document.getElementById('loadingContainer').innerHTML = '<div class="loader"></div><div class="loading-text">加载中...</div>';
                    }
                } else {
                    hasMore = false;
                    document.getElementById('loadingContainer').innerHTML = '<div class="loading-text">暂无更多图片</div>';
                }
            } catch (e) {
                console.error(e);
                document.getElementById('loadingContainer').innerHTML = '<div class="loading-text">加载失败，请刷新重试</div>';
            } finally {
                isLoading = false;
            }
        }
        
        // 追加图片到瀑布流
        function appendImages(images) {
            const waterfall = document.getElementById('waterfall');
            
            images.forEach(img => {
                const card = document.createElement('div');
                card.className = 'image-card';
                card.onclick = () => openModal(img.url);
                
                const imgElement = document.createElement('img');
                imgElement.src = `/image/${encodeURIComponent(img.url)}`;
                imgElement.alt = img.title;
                imgElement.loading = 'lazy';
                
                const overlay = document.createElement('div');
                overlay.className = 'image-overlay';
                overlay.innerHTML = `<div class="image-title">${escapeHtml(img.title.substring(0, 40))}</div>`;
                
                card.appendChild(imgElement);
                card.appendChild(overlay);
                waterfall.appendChild(card);
            });
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function openModal(url) {
            const modal = document.getElementById('modal');
            const modalImg = document.getElementById('modalImg');
            modal.classList.add('active');
            modalImg.src = `/image/${encodeURIComponent(url)}`;
        }
        
        function closeModal() {
            document.getElementById('modal').classList.remove('active');
        }
        
        // 回到顶部
        function scrollToTop() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        
        // 滚动监听 - 无限加载
        function setupInfiniteScroll() {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting && !isLoading && hasMore) {
                        loadMoreImages();
                    }
                });
            }, { threshold: 0.1 });
            
            observer.observe(document.getElementById('loadingContainer'));
        }
        
        // 回到顶部按钮显示/隐藏
        window.addEventListener('scroll', () => {
            const btn = document.getElementById('backToTop');
            if (window.scrollY > 500) {
                btn.classList.add('show');
            } else {
                btn.classList.remove('show');
            }
        });
        
        // 键盘ESC关闭弹窗
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });
        
        // 初始化
        buildNav();
        setupInfiniteScroll();
        loadMoreImages();
    </script>
</body>
</html>'''
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def serve_list_api(self, category_code):
        """API: 返回某分类某页的图片列表"""
        query = urlparse(self.path).query
        page = 1
        if query.startswith('page='):
            try:
                page = int(query.split('=')[1])
            except:
                pass
        
        # 检查缓存
        cache_key = f"{category_code}_{page}"
        with self.cache_lock:
            if cache_key in self.cache:
                result = self.cache[cache_key]
                self.send_json_response(result)
                return
        
        # 构造列表页URL
        if page == 1:
            list_url = f"{self.base_url}{category_code}.html"
        else:
            list_url = f"{self.base_url}{category_code}_{page}.html"
        
        try:
            resp = self.session.get(list_url, timeout=10)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 提取详情页链接 —— 增强版，适配更多页面结构
            image_list = []
            # 尝试多个可能的图片容器选择器
            possible_selectors = ['div.list-com a', 'div.list-pic a', 'div.pic-list a', 'ul.list-pic li a', 'div.pic-box a']
            found_links = []

            for selector in possible_selectors:
                elements = soup.select(selector)
                if elements:
                    found_links = elements
                    break  # 找到第一个有效的就停止

            # 如果还是没找到，再用更宽泛的方法找所有带href的a标签，并过滤出像详情页的链接
            if not found_links:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    # 过滤出详情页链接，通常包含 .html 且不是分页链接
                    if '.html' in href and 'page' not in href and href not in ['#', 'javascript:void(0)']:
                        found_links.append(a)

            # 从找到的链接中提取URL
            for a in found_links[:30]:  # 限制最多30个，防止太多
                detail_url = urljoin(self.base_url, a['href'])
                # 简单去重
                if detail_url not in [item['url'] for item in image_list]:
                    images, title = self.get_detail_images(detail_url)
                    for img_url in images:
                        image_list.append({
                            'url': img_url,
                            'title': title or '未命名'
                        })
                    # 加个小延迟，避免请求太快
                    time.sleep(0.2)            
            # 检查下一页
            has_next = self.has_next_page(category_code, page + 1)
            
            result = {
                'images': image_list,
                'hasNext': has_next,
                'page': page
            }
            
            # 缓存（简单缓存5分钟）
            with self.cache_lock:
                self.cache[cache_key] = result
            
            self.send_json_response(result)
            
        except Exception as e:
            self.send_json_response({'error': str(e), 'images': [], 'hasNext': False}, status=500)
    
    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def get_detail_images(self, detail_url):
        """从详情页提取图片URL"""
        try:
            resp = self.session.get(detail_url, timeout=10)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            images = []
            for img in soup.find_all('img', src=True):
                src = img['src']
                if src.startswith('http'):
                    images.append(src)
                else:
                    images.append(urljoin(detail_url, src))
            
            # 去重
            images = list(dict.fromkeys(images))
            
            # 提取标题
            title = ''
            title_elem = soup.find('h1')
            if title_elem:
                title = title_elem.get_text(strip=True)
            if not title:
                title = detail_url.split('/')[-1].replace('.html', '')
            
            return images, title
        except:
            return [], ''
    
    def has_next_page(self, category_code, page):
        """检查下一页是否存在"""
        if page == 1:
            url = f"{self.base_url}{category_code}.html"
        else:
            url = f"{self.base_url}{category_code}_{page}.html"
        try:
            resp = self.session.head(url, timeout=5)
            return resp.status_code == 200
        except:
            return False
    
    def proxy_image(self, encoded_url):
        """代理图片请求"""
        try:
            img_url = unquote(encoded_url)
            headers = {
                'Referer': self.base_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            resp = self.session.get(img_url, headers=headers, timeout=15, stream=True)
            
            if resp.status_code == 200:
                content_type = resp.headers.get('content-type', '')
                if 'image' in content_type:
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    
                    for chunk in resp.iter_content(chunk_size=8192):
                        self.wfile.write(chunk)
                else:
                    self.send_error(404, 'Not an image')
            else:
                self.send_error(404, 'Image not found')
        except Exception as e:
            self.send_error(500, str(e))

def main():
    port = 5000
    server = HTTPServer(('0.0.0.0', port), WaterfallImageHandler)
    print(f"\n✅ 瀑布流看图服务已启动")
    print(f"📍 访问地址: http://localhost:{port}")
    print(f"🎨 特性: 瀑布流 | 无限滚动 | 点击放大")
    print(f"\n按 Ctrl+C 停止服务\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")

if __name__ == '__main__':
    main()
    