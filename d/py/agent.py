# agent.py 跨平台简易Agent
import os
import sys
import json
import platform
import sqlite3
import time
import re
from datetime import datetime, timedelta
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 修复：Windows GBK 控制台打印 emoji（✅🧹🆕📦🔧等）会抛 UnicodeEncodeError，
# 强制 stdout/stderr 使用 UTF-8 输出并容错替换，确保 emoji 打印不崩溃
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ===================== 配置区 =====================
API_KEY = os.getenv("AGNES_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://apihub.agnes-ai.com/v1")

# 修复：云端模型名通过环境变量 AGNES_MODEL 覆盖（默认 agnes-2.5-flash），消除双处硬编码
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-2.5-flash")
# 修复：上下文压缩 token 阈值提取为常量（v0.13.1: 12000 → 100000，适配 agnes-2.5-flash 512K 窗口）
COMPRESS_TOKEN_THRESHOLD = 100000

LOCAL_BASE_URL = os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "ollama")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "llama")

MAX_TURNS = 100
MAX_TURNS_COMPRESS_THRESHOLD = 60  # 达到此轮数时触发上下文压缩（兜底）
TEMPERATURE = 0.05
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 安全：高危命令黑名单
# 注意：高危shell黑名单仅字符串匹配，可被迂回绕过，为本机简易防护，切勿对外网开放访问。
DANGEROUS_CMDS = [
    "rm -rf /", "rm -rf /*", "del /f /s /q C:\\", 
    "format", "mkfs", "dd if=", "cat /etc/shadow",
    "sudo", "chmod 777 /", "chown -R", "kill -9 1"
]

# ===================== 记忆系统 =====================
MEMORY_DB = os.path.join(SCRIPT_DIR, "agent_memory.db")

def _get_conn():
    conn = sqlite3.connect(MEMORY_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _init_memory_table():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            tags TEXT,
            created_at TEXT
        )
    """)
    # 临时记忆日志表：记录工具调用，方便排查Agent行为
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            tool_name TEXT,
            args TEXT,
            result_summary TEXT
        )
    """)
    conn.commit()
    conn.close()

# 启动时清理7天以上的临时记忆（上下文压缩产生的摘要）
def _cleanup_temp_memories():
    conn = _get_conn()
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    deleted = conn.execute(
        "DELETE FROM memories WHERE tags = 'temp_context' AND created_at < ?",
        (seven_days_ago,)
    ).rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        print(f"🧹 已清理 {deleted} 条超过7天的临时记忆")

_init_memory_table()
_cleanup_temp_memories()

def save_memory(title: str, content: str, tags: str = "") -> str:
    """将用户指定的内容存入记忆库"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO memories (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
        (title, content, tags, now)
    )
    conn.commit()
    conn.close()
    return f"✅ 记忆已保存 [{title}] 标签: {tags or '无'}"

def list_memories() -> str:
    """列出所有记忆"""
    conn = _get_conn()
    cursor = conn.execute("SELECT id, title, tags, created_at FROM memories ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return "📭 记忆库为空"
    lines = [f"共有 {len(rows)} 条记忆："]
    for r in rows:
        lines.append(f"  #{r[0]} {r[1]} | 标签:{r[2]} | {r[3]}")
    return "\n".join(lines)

def update_memory(mem_id: int, title: str = None, content: str = None, tags: str = None) -> str:
    """修改指定记忆"""
    conn = _get_conn()
    row = conn.execute("SELECT id FROM memories WHERE id = ?", (mem_id,)).fetchone()
    if not row:
        conn.close()
        return f"❌ 未找到 ID 为 {mem_id} 的记忆"
    updates = []
    values = []
    if title is not None:
        updates.append("title = ?")
        values.append(title)
    if content is not None:
        updates.append("content = ?")
        values.append(content)
    if tags is not None:
        updates.append("tags = ?")
        values.append(tags)
    if updates:
        values.append(mem_id)
        conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
    conn.close()
    return f"✅ 已更新记忆 #{mem_id}"

def delete_memory(mem_id: int) -> str:
    """删除指定记忆"""
    conn = _get_conn()
    row = conn.execute("SELECT id, title FROM memories WHERE id = ?", (mem_id,)).fetchone()
    if not row:
        conn.close()
        return f"❌ 未找到 ID 为 {mem_id} 的记忆"
    conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
    conn.commit()
    conn.close()
    return f"🗑️ 已删除记忆 #{mem_id} [{row[1]}]"

def query_memory(keyword: str) -> str:
    """模糊检索记忆库，返回匹配结果"""
    # 当前记忆检索为SQL LIKE文本匹配，不做向量改造，保留现状，后续需要语义检索再扩展。
    conn = _get_conn()
    # 修复：转义 LIKE 通配符（\ % _），避免关键词含 % 或 _ 时匹配到全部记录
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_pattern = f"%{escaped}%"
    # 修复：限制最多返回 10 条，避免结果过多刷屏
    cursor = conn.execute(
        "SELECT id, title, content, tags, created_at FROM memories "
        "WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' "
        "LIMIT 10",
        (like_pattern, like_pattern, like_pattern)
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return f"🔍 未找到与 '{keyword}' 相关的记忆"
    results = []
    for r in rows:
        results.append(f"[#{r[0]}] {r[1]} | 标签: {r[3]} | 时间: {r[4]}\n   {r[2]}")
    return f"📚 找到 {len(rows)} 条记忆:\n" + "\n---\n".join(results)

def build_system_context(user_query: str = ""):
    """查询与当前对话相关的记忆，注入系统提示"""
    try:
        # 优先使用当前用户查询作为关键词，避免依赖旧 current_messages
        keyword = user_query.strip()[:30] if user_query else ""
        if not keyword:
            return ""
        result = query_memory(keyword)
        if "📚 找到" in result:
            return f"\n【相关记忆】\n{result}"
    except Exception as e:
        print(f"⚠️ build_system_context 错误: {e}")
    return ""

# ================================================

MODEL_LIST = [AGNES_MODEL, "llama"]
current_model = AGNES_MODEL

def get_client(model_name):
    if model_name == "llama":
        return OpenAI(api_key=LOCAL_API_KEY, base_url=LOCAL_BASE_URL)
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)

def get_model_name(model_name):
    if model_name == "llama":
        return LOCAL_MODEL
    return AGNES_MODEL

client = get_client(current_model)

IS_WIN = platform.system() == "Windows"
IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "")

# ===================== Token计数（用于压缩触发） =====================
_token_counter = None
try:
    import tiktoken
    _token_counter = tiktoken.encoding_for_model("gpt-4")
    print("✅ 使用tiktoken进行token计数")
except ImportError:
    _token_counter = None
    print("⚠️ tiktoken未安装，使用近似估算token计数")

def count_tokens_approx(text) -> int:
    """统计token数量，优先使用tiktoken，失败时回退到近似估算"""
    if not text or not isinstance(text, str):
        return 0
    try:
        if _token_counter is not None:
            return len(_token_counter.encode(text))
    except Exception as e:
        print(f"⚠️ tiktoken计数失败，回退到近似估算: {e}")
    # 简单估算：中文字符和英文单词混合
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = len(text) - cn_chars
    return cn_chars // 2 + en_chars // 4

# P0 FIX: 完整的消息token计数函数，包含 tool_calls 中的 arguments
def count_message_tokens(msg: dict) -> int:
    """计算单条消息的token数，包括content和tool_calls中的arguments"""
    if not isinstance(msg, dict):
        return 0
    
    total = 0
    
    # 计算 content 字段
    content = msg.get("content", "")
    if content and isinstance(content, str):
        total += count_tokens_approx(content)
    
    # 计算 tool_calls 字段
    tool_calls = msg.get("tool_calls", [])
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                # 计算 tool_calls 每个字段的token
                func = tc.get("function", {})
                if isinstance(func, dict):
                    name = func.get("name", "")
                    args_json = func.get("arguments", "")
                    total += count_tokens_approx(name)
                    total += count_tokens_approx(args_json)
                # id 字段
                tc_id = tc.get("id", "")
                total += count_tokens_approx(tc_id)
    
    return total

# ===================== 对话状态 =====================
current_messages = None
current_dialog_turn = 0  # P1: 用户对话轮次计数
compression_attempted = False  # 修复：压缩失败标记提升为模块级全局变量，压缩失败后本进程内不再每轮重复尝试

def new_conversation():
    global current_messages, current_dialog_turn, compression_attempted
    current_messages = None
    current_dialog_turn = 0
    compression_attempted = False
    return "🆕 已创建新对话，上下文已清空"

def reset_context(user_query: str, messages: list) -> tuple[list, int]:
    """压缩上下文：用 LLM 摘要历史对话，存入临时记忆，返回新的 messages 列表和重置后的轮次"""
    print("\n📦 上下文过长，正在压缩历史对话...")
    
    # 保留原始Agent系统提示词
    original_system = None
    first_user_msg = None  # P1 FIX: 保留第一条用户消息
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            original_system = msg.get("content", "")
        elif isinstance(msg, dict) and msg.get("role") == "user" and first_user_msg is None:
            first_user_msg = msg.get("content", "")  # 保存第一条用户消息
    
    sys_msg = {
        "role": "system",
        "content": (
            "你是一个对话摘要助手。请将以下对话历史压缩为一段简洁摘要，"
            "保留所有重要事实、已完成的工具和结论，但不要包含对话过程细节。\n"
            "格式：\n【摘要】...（最多 500 字）\n【原始问题】...（一句话）"
        )
    }
    retry_count, max_retries = 0, 3
    while True:
        try:
            # P1 FIX: 显式把第一条 user 消息拼到 recent 前面，确保摘要包含原始问题
            recent = [m for m in (messages[-20:] if len(messages) > 20 else messages)
                      if not (isinstance(m, dict) and m.get("role") == "system")]
            if first_user_msg and recent and recent[0].get("role") != "user":
                # 如果 recent 的第一条不是 user，且我们保存了第一条用户消息，则插入到前面
                recent.insert(0, {"role": "user", "content": first_user_msg})
            
            resp = client.chat.completions.create(
                model=get_model_name(current_model),
                messages=[sys_msg] + recent,
                temperature=0.1
            )
            # 修复：choices 为空或 content 为 None 时避免崩溃
            if not resp.choices:
                return messages, 0
            summary = (resp.choices[0].message.content or "").strip()
            if not summary:
                print("⚠️ 摘要模型返回空内容，跳过压缩")
                return messages, 0
            break
        except RateLimitError as e:
            retry_count += 1
            err_body = {}
            try:
                err_body = e.response.json() if e.response else {}
            except Exception:
                pass
            if any(kw in str(err_body.get("message", "")).lower()
                   for kw in ["quota", "credit", "token plan", "upgrade", "free user"]):
                if "llama" in MODEL_LIST:
                    print("🔄 配额耗尽，降级到本地模型压缩上下文...")
                    switch_model("llama")
                    try:
                        # 修复：降级分支的 recent 列表同样过滤 system 消息，与主分支保持一致
                        recent = [m for m in (messages[-20:] if len(messages) > 20 else messages)
                                  if not (isinstance(m, dict) and m.get("role") == "system")]
                        if first_user_msg and recent and recent[0].get("role") != "user":
                            recent.insert(0, {"role": "user", "content": first_user_msg})
                        resp = client.chat.completions.create(
                            model=get_model_name(current_model),
                            messages=[sys_msg] + recent,
                            temperature=0.1
                        )
                        # 修复：choices 为空或 content 为 None 时避免崩溃
                        if not resp.choices:
                            return messages, 0
                        summary = (resp.choices[0].message.content or "").strip()
                        if not summary:
                            print("⚠️ 本地模型摘要返回空内容，跳过压缩")
                            return messages, 0
                        break
                    except Exception as e2:
                        print(f"❌ 本地模型压缩也失败: {e2}")
                        return messages, 0
                return messages, 0
            if retry_count > max_retries:
                print(f"❌ 限流，跳过上下文压缩")
                return messages, 0
            wait = min(2 ** retry_count, 10)
            print(f"⚠️ 限流，等待 {wait}s 后重试压缩 ({retry_count}/{max_retries})...")
            time.sleep(wait)
        except Exception as e:
            # 修复：非限流类 API 异常（断连/认证/超时等）不再冒泡崩溃，跳过压缩
            print(f"❌ 摘要生成异常: {e}，跳过上下文压缩")
            return messages, 0

    print(f"✅ 上下文已压缩，摘要长度: {len(summary)} 字")
    save_memory(f"对话摘要 {datetime.now().strftime('%H:%M')}", summary, "temp_context")

    # 保留原始系统提示词
    new_system_content = original_system if original_system else (
        "你是本机终端智能助手，可以使用提供的工具完成用户任务。"
    )
    
    # P1 FIX: 修压缩后 system 里「原始问题：」残缺 - 直接拼接 user_query
    new_messages = [
        {
            "role": "system",
            "content": (
                f"{new_system_content}\n\n"
                "以下是之前的对话摘要，请基于它继续帮助用户：\n"
                f"{summary}\n\n"
                f"当前问题：{user_query}"
            )
        },
        {"role": "user", "content": user_query}
    ]
    print("📋 已创建新对话轮次，上下文已重置\n")
    return new_messages, 0

tools = [
    {
        "type": "function",
        "function": {
            "name": "shell_run",
            "description": "执行本机终端命令，Windows使用powershell，Linux/Termux使用bash",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文本文件内容",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入/覆盖文本文件",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
        }
    }
]

def shell_run(cmd: str, **kwargs):
    """执行shell命令，带安全检查和超时处理"""
    import subprocess

    # 安全检查：高危命令黑名单（按空格分词后比对，避免误拦子字符串）
    cmd_lower = cmd.lower().strip()
    tokens = set(cmd_lower.split())
    for dangerous in DANGEROUS_CMDS:
        d_tokens = dangerous.lower().split()
        if all(t in tokens for t in d_tokens):
            return f"⛔ 安全拦截：命令包含高危操作 '{dangerous}'，已拒绝执行"

    # 修复：等号/无空格模式（如 dd if=...、mkfs、chmod 777 /）按空格分词无法匹配，改用正则
    eq_patterns = [
        r"dd\s+if=/",          # 读取块设备/文件
        r"dd\s+of=/",          # 修复：向块设备/磁盘写入（如 dd if=/dev/zero of=/dev/sda 可覆盖磁盘）
        r"mkfs\.",             # 创建文件系统
        r"chmod\s+777\s+/",    # 根目录全权限
        r"chown\s+-r\s*/",     # 递归改属主到根
        r"format\s+[a-z]:",    # Windows 磁盘格式化
    ]
    for pat in eq_patterns:
        if re.search(pat, cmd_lower):
            return f"⛔ 安全拦截：命令匹配高危模式 '{pat}'，已拒绝执行"

    # P0 FIX: 修复正则 group 索引错误 - rm_match.group(3) → group(2)
    # 正则只有2个捕获组：flag (第1组) 和 target (第2组)
    rm_match = re.search(r"(?:^|[;&|]{1,2}\s*)\s*rm\s+(-[a-z]*r[a-z]*f?|[a-z]*f[a-z]*r?)?\s+(\S+)", cmd_lower)
    if rm_match:
        target = rm_match.group(2).strip("'\"").rstrip("/\\")  # P0 FIX: group(3) → group(2)
        home_path = os.path.expanduser("~")
        protected = {"", "/", "*", "~", "$HOME", home_path, "/root", "/etc", "/usr", "/var",
                     "/bin", "/sbin", "/boot", "/lib", "/lib64", "/dev", "/proc", "/sys"}
        # 修复：补充 Windows 常见危险路径（Windows 下 target 以盘符反斜杠出现，保护判断不区分大小写）
        win_protected = {"c:", "c:\\windows", "c:\\program files", "c:\\program files (x86)",
                         "c:\\users", "c:\\programdata", "c:\\recovery",
                         "c:\\system volume information", "c:\\$recycle.bin"}
        target_lower = target.lower()
        # Termux 特有保护路径
        termux_protected = {"/data/data", "/data/data/com.termux",
                            "/data/data/com.termux/files"}
        if target_lower in termux_protected or target_lower.startswith("/data/data/"):
            return f"⛔ 安全拦截：拒绝删除 Termux 系统路径 '{rm_match.group(2)}'，已拒绝执行"
        if (target in protected or target_lower in win_protected
                or target.startswith(("/home/", "/root/"))
                or target_lower.startswith(("c:\\windows\\", "c:\\program files\\",
                                            "c:\\program files (x86)\\", "c:\\users\\",
                                            "c:\\programdata\\"))):
            return f"⛔ 安全拦截：拒绝删除受保护路径 '{rm_match.group(2)}'，已拒绝执行"
    
    try:
        if IS_WIN:
            # 修复：显式指定 UTF-8 编码，避免中文乱码（GBK 环境默认编码）
            proc = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=120)
        elif IS_TERMUX:
            # Termux 使用 bash（路径固定）
            proc = subprocess.run(cmd, shell=True, executable="/data/data/com.termux/files/usr/bin/bash", 
                capture_output=True, text=True, timeout=120)
        else:
            # Linux/macOS 使用 SHELL 环境变量
            proc = subprocess.run(cmd, shell=True, executable=os.environ.get("SHELL", "/bin/sh"), 
                capture_output=True, text=True, timeout=120)
        
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
        
        # 截断并警告
        if len(stdout) > 12000:
            stdout = stdout[:12000] + "\n... [输出已截断，超过12000字符]"
        if len(stderr) > 12000:
            stderr = stderr[:12000] + "\n... [错误输出已截断，超过12000字符]"
            
        return f"stdout:\n{stdout}\nstderr:\n{stderr}\nreturncode:{returncode}"
    except subprocess.TimeoutExpired:
        return "error:执行超时（超过120秒），请检查命令是否需要长时间运行"
    except Exception as e:
        return f"error:{str(e)}"

def read_file(path: str, **kwargs):
    """读取文件，限制路径在脚本目录内，截断8000字符"""
    # 安全限制：禁止读取脚本目录之外的文件
    abs_path = os.path.realpath(os.path.abspath(path))
    script_dir = os.path.realpath(SCRIPT_DIR)
    try:
        if os.path.commonpath([abs_path, script_dir]) != script_dir:
            return f"⛔ 安全拦截：禁止读取脚本目录之外的文件 ({path})"
    except ValueError:
        # Windows 跨盘符时 commonpath 抛异常，视为不允许访问
        return f"⛔ 安全拦截：禁止读取脚本目录之外的文件 ({path})"

    # 修复：禁止读取敏感配置文件（含密钥/凭据）
    fname = os.path.basename(abs_path).lower()
    if fname in (".env", ".git-credentials", ".netrc", "id_rsa", "id_ed25519", "known_hosts") \
            or fname.endswith((".pem", ".key", ".p12")):
        return f"⛔ 安全拦截：禁止读取敏感文件 ({path})"

    # 修复：限制读取文件大小，避免超大文件整体读入内存
    try:
        if os.path.getsize(abs_path) > 2 * 1024 * 1024:
            return f"⛔ 安全拦截：文件过大（{os.path.getsize(abs_path)} 字节，上限 2MB），拒绝读取"
    except OSError:
        pass

    try:
        # 修复：errors="replace" 避免 GBK 等编码文件读取报错
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 8000:
            content = content[:8000] + "\n... [内容已截断，超过8000字符]"
        return content
    except Exception as e:
        return f"read error:{str(e)}"

def write_file(path: str, content: str, **kwargs):
    """写入文件，限制路径在脚本目录内"""
    # 安全限制：禁止写入脚本目录之外的文件
    abs_path = os.path.realpath(os.path.abspath(path))
    script_dir = os.path.realpath(SCRIPT_DIR)
    try:
        if os.path.commonpath([abs_path, script_dir]) != script_dir:
            return f"⛔ 安全拦截：禁止写入脚本目录之外的文件 ({path})"
    except ValueError:
        # Windows 跨盘符时 commonpath 抛异常，视为不允许访问
        return f"⛔ 安全拦截：禁止写入脚本目录之外的文件 ({path})"

    # 修复：禁止覆盖敏感配置文件（含密钥/凭据）
    fname = os.path.basename(abs_path).lower()
    if fname in (".env", ".git-credentials", ".netrc", "id_rsa", "id_ed25519") \
            or fname.endswith((".pem", ".key", ".p12")):
        return f"⛔ 安全拦截：禁止写入敏感文件 ({path})"
    
    try:
        # 修复：path 无目录部分（如 "test.txt"）时 dirname 返回空串，兜底为 "."
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return "write ok"
    except Exception as e:
        return f"write error:{str(e)}"

tool_map = {"shell_run": shell_run, "read_file": read_file, "write_file": write_file}

def switch_model(model_name):
    global current_model, client
    if model_name not in MODEL_LIST:
        print(f"⚠️ 未知模型: {model_name}，可用: {', '.join(MODEL_LIST)}")
        return False
    if current_model != model_name and current_messages:
        print("⚠️ 复用现有上下文，若切换为小窗口模型可能超出token限制，输入new清空对话")
    current_model = model_name
    client = get_client(model_name)
    print(f"✅ 已切换到模型: {get_model_name(model_name)}")
    return True

def log_tool_call(tool_name: str, args: dict, result: str):
    """记录工具调用日志到sqlite"""
    try:
        conn = _get_conn()
        # 修复：日志脱敏，避免密钥/Token 等敏感信息明文落库
        safe_args = dict(args or {})
        for k in list(safe_args.keys()):
            if any(s in k.lower() for s in ("key", "token", "secret", "password", "api")):
                safe_args[k] = "***"
        safe_result = result
        # P2 FIX: 日志脱敏改用正则精确匹配，避免误拦
        # 匹配真实的密钥格式（如 sk- 后跟20+位字母数字）
        sensitive_patterns = [
            r'sk-[A-Za-z0-9]{20,}',  # OpenAI 密钥格式
            r'api[_-]?key[=:\s]+[A-Za-z0-9_-]{10,}',  # api_key=xxx
            r'token[=:\s]+[A-Za-z0-9_-]{10,}',  # token=xxx
            r'password[=:\s]+\S+',  # password=xxx
            r'secret[=:\s]+[A-Za-z0-9_-]{10,}',  # secret=xxx
        ]
        for pattern in sensitive_patterns:
            safe_result = re.sub(pattern, "[REDACTED]", safe_result, flags=re.IGNORECASE)
        
        summary = safe_result[:100] + "..." if len(safe_result) > 100 else safe_result
        conn.execute(
            "INSERT INTO tool_log (timestamp, tool_name, args, result_summary) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tool_name, json.dumps(safe_args, ensure_ascii=False), summary)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 工具日志记录失败: {e}")

def agent_loop(user_query: str):
    global current_messages, current_dialog_turn, compression_attempted

    # P1 FIX: 使用 dialog_turn 记录用户对话轮次，不与 tool_turn 混淆
    current_dialog_turn += 1
    tool_turn = 0  # 工具调用轮次单独计数

    # 新建对话指令
    if user_query.strip() in ["新建对话", "new", "new对话", "新对话", "清空对话"]:
        print(new_conversation())
        return

    # 处理记忆指令
    if user_query.startswith("记忆：") or user_query.startswith("记忆:"):
        parts = user_query[3:].split(" ", 1)
        title = parts[0] if parts else "未命名"
        content = parts[1] if len(parts) > 1 else ""
        tags = ""
        if "#" in content:
            tag_part = content.split("#")[1].strip()
            content = content.split("#")[0].strip()
            tags = tag_part
        print(save_memory(title, content, tags))
        return

    # 列出所有记忆
    if user_query.strip() in ["记忆列表", "查看记忆", "list记忆"]:
        print(list_memories())
        return

    # 修改记忆 - 加try-except捕获数字转换错误
    if user_query.startswith("修改记忆") or user_query.startswith("改记忆"):
        rest = user_query.replace("修改记忆", "").replace("改记忆", "").strip()
        if rest.startswith("#"):
            parts = rest[1:].split(" ", 2)
            try:
                mem_id = int(parts[0])
            except ValueError:
                print(f"❌ 记忆ID必须是数字，当前输入: {parts[0]}")
                return
            new_title = parts[1] if len(parts) > 1 else None
            new_content = parts[2] if len(parts) > 2 else None
            tags = ""
            if new_content and "#" in new_content:
                tags = new_content.split("#")[-1].strip()
                new_content = new_content.split("#")[0].strip()
            print(update_memory(mem_id, title=new_title, content=new_content, tags=tags))
        else:
            print("📝 格式：修改记忆 #ID 新内容")
        return

    # 删除记忆 - 加try-except捕获数字转换错误
    if user_query.startswith("删除记忆") or user_query.startswith("删记忆"):
        rest = user_query.replace("删除记忆", "").replace("删记忆", "").strip()
        if rest.startswith("#"):
            try:
                mem_id = int(rest[1:])
            except ValueError:
                print(f"❌ 记忆ID必须是数字，当前输入: {rest[1:]}")
                return
            print(delete_memory(mem_id))
        else:
            print("📝 格式：删除记忆 #ID")
        return

    # 查询记忆时不覆盖全局对话上下文，仅打印结果后直接返回
    if user_query.startswith("查询记忆") or user_query.startswith("查记忆"):
        keyword = user_query.replace("查询记忆", "").replace("查记忆", "").strip()
        if keyword:
            result = query_memory(keyword)
            print(result)
            return
        else:
            print("📝 请输入关键词，例如：查询记忆 AI")
            return
    else:
        # 使用全局对话状态（不立即清空，防止上下文丢失）
        messages = list(current_messages) if current_messages else []
        system_content = (
            "你是本机终端智能助手，可以使用提供的工具完成用户任务。\n"
            "规则：\n"
            "1. 执行命令、读写文件必须使用function-call工具，禁止直接把命令用文本发出来。\n"
            "2. 禁止编造工具或参数，严格按工具定义传入参数。\n"
            "3. 信息充分时直接输出总结，主动停止工具调用。\n"
            "4. 不要无意义重复检索，多次查询不到则判定不存在。\n"
            "5. 不要无限循环调用工具，问题明确后及时给出结论。\n"
            "6. 使用「记忆：标题 内容 #标签」保存重要信息。\n"
            "7. 使用「查询记忆 关键词」检索已有记忆。\n"
            "8. 使用「记忆列表」查看所有记忆。\n"
            "9. 使用「修改记忆 #ID 新内容」修改记忆。\n"
            "10. 使用「删除记忆 #ID」删除记忆。"
        )
        # 注入记忆上下文（传入当前 user_query 作为关键词）
        memory_context = build_system_context(user_query)
        if memory_context:
            system_content += memory_context
        
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_content
        else:
            messages.insert(0, {"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_query})

    actual_model = get_model_name(current_model)
    print(f"\n📡使用模型: {actual_model}")
    
    # P0 FIX: 计算总token数，包含 tool_calls
    total_tokens = sum(count_message_tokens(m) if isinstance(m, dict) else 0 for m in messages)

    # 修复：压缩失败标记为模块级全局变量（compression_attempted），
    # 压缩失败后本进程内不再每轮重复尝试；新对话（new）时由 new_conversation 重置

    # 修复：改用 while 循环，压缩重置轮次后不丢失剩余迭代额度
    while tool_turn < MAX_TURNS:
        # P1 FIX: 使用 dialog_turn 和 tool_turn 分别判断，避免语义混淆
        # 检测是否接近上限，触发上下文压缩（以token为主，轮数为兜底）
        if (total_tokens > COMPRESS_TOKEN_THRESHOLD or tool_turn >= MAX_TURNS_COMPRESS_THRESHOLD) and tool_turn < MAX_TURNS:
            if compression_attempted:
                # P0 FIX: 压缩失败后硬截断兜底 - 保留 system + 最近 N 条消息
                print("⚠️ 上下文压缩失败，本进程内不再重复尝试压缩，执行硬截断...")
                # 安全截断：保留 system + 从最近 user 消息开始的完整对话，避免孤立 tool 消息
                head = messages[:1]  # 只保 system
                tail_start = len(messages) - 1
                while tail_start > 0 and messages[tail_start].get("role") != "user":
                    tail_start -= 1
                messages = head + messages[tail_start:]
                total_tokens = sum(count_message_tokens(m) if isinstance(m, dict) else 0 for m in messages)
            else:
                new_messages, new_tool_turn = reset_context(user_query, messages)
                if new_messages is messages and new_tool_turn == 0:
                    # 压缩失败，保持原有轮次计数，标记本进程内跳过压缩
                    print("⚠️ 上下文压缩失败，本进程内不再重复尝试压缩")
                    compression_attempted = True
                else:
                    messages, tool_turn = new_messages, new_tool_turn
                    compression_attempted = False
                    actual_model = get_model_name(current_model)
                    total_tokens = sum(count_message_tokens(m) if isinstance(m, dict) else 0 for m in messages)
        # 处理 API 限流：指数退避重试
        retry_count = 0
        max_retries = 3
        while True:
            try:
                resp = client.chat.completions.create(
                    model=actual_model,
                    messages=messages,
                    tools=tools,
                    temperature=TEMPERATURE
                )
                break
            except RateLimitError as e:
                retry_count += 1
                err_body = {}
                try:
                    err_body = e.response.json() if e.response else {}
                except Exception:
                    pass
                is_quota_exhausted = any(
                    kw in str(err_body.get("message", "")).lower()
                    for kw in ["quota", "credit", "token plan", "upgrade", "free user"]
                )
                if is_quota_exhausted:
                    print(f"❌ API 配额已耗尽，无法通过重试恢复")
                    if "llama" in MODEL_LIST:
                        print("🔄 自动降级到本地模型 llama...")
                        switch_model("llama")
                        actual_model = get_model_name(current_model)
                        try:
                            resp = client.chat.completions.create(
                                model=actual_model,
                                messages=messages,
                                tools=tools,
                                temperature=TEMPERATURE
                            )
                            break
                        except Exception as e2:
                            print(f"❌ 本地模型调用也失败: {e2}")
                    # 修复：异常退出前保存当前状态，避免压缩后的新上下文丢失
                    current_messages = messages
                    return
                if retry_count > max_retries:
                    print(f"❌ API 限流，已重试 {max_retries} 次，跳过本轮对话")
                    # 修复：异常退出前保存当前状态
                    current_messages = messages
                    return
                wait_time = min(2 ** retry_count, 10)
                print(f"⚠️ API 限流，等待 {wait_time} 秒后重试 ({retry_count}/{max_retries})...")
                time.sleep(wait_time)
            except Exception as e:
                # 修复：非限流类 API 异常（网络断连/APIConnectionError/AuthenticationError/超时等）不崩溃，
                # 打印错误、保存状态后返回，主循环继续
                print(f"❌ API 调用异常: {e}，跳过本轮")
                current_messages = messages
                return
        # 修复：choices 为空时避免 IndexError 崩溃
        if not resp.choices:
            print("⚠️ API 返回空 choices，跳过本轮")
            current_messages = messages
            return
        msg = resp.choices[0].message
        if not msg.tool_calls:
            print(f"\n🤖Agent:\n{msg.content}")
            # 修复：将最终回复也加入上下文，避免下一轮模型丢失自己上一轮的回答
            messages.append(msg.model_dump() if hasattr(msg, "model_dump") else msg.dict())
            # 保存当前对话状态
            current_messages = messages
            return
        messages.append(msg.model_dump() if hasattr(msg, "model_dump") else msg.dict())
        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                # P1 FIX: 工具参数 JSON 解析失败时，回传错误让模型重试，而不是静默传空 dict
                error_msg = f"❌ 参数解析失败: 无效的 JSON 格式 '{tc.function.arguments}'"
                print(f"⚠️ {error_msg}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": error_msg
                })
                continue  # 跳过本次工具调用，让模型重新生成
            if fname not in tool_map:
                res = f"error: 未知工具 {fname}"
                args = {}
            else:
                # 修复：打印前脱敏，避免含密码/密钥的命令参数明文泄露到 stdout
                safe_args = dict(args or {})
                for k in list(safe_args.keys()):
                    if any(s in k.lower() for s in ("key", "token", "secret", "password", "api")):
                        safe_args[k] = "***"
                print(f"\n🔧调用工具 {fname} → {safe_args}")
                try:
                    res = tool_map[fname](**args)
                except Exception as e:
                    res = f"error: 工具执行异常 {e}"
            # 记录工具调用日志
            log_tool_call(fname, args, res)
            # 修复：工具返回为 None 时兜底为空串，避免 len(None) 崩溃
            if res is None:
                res = ""
            # 截断tool输出并警告
            if len(res) > 12000:
                res = res[:12000] + "\n... [工具输出已截断，超过12000字符]"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": res
            })
        tool_turn += 1
        # P0 FIX: 更新token计数时使用新的 count_message_tokens 函数
        total_tokens = sum(count_message_tokens(m) if isinstance(m, dict) else 0 for m in messages)
    
    print(f"\n⚠️已到达最大轮次 {MAX_TURNS}，自动停止。")
    # 保存当前对话状态
    current_messages = messages
if __name__ == "__main__":
    if not API_KEY:
        print("⚠️ 错误：未在 .env 文件中找到 AGNES_API_KEY")
        print("请在 .env 文件中添加：AGNES_API_KEY=你的密钥")
        exit(1)

    print("✅ API Key 已加载")
    plat = "Termux" if IS_TERMUX else ("Windows" if IS_WIN else "Linux")
    print(f"✅Openai_Agent已启动，检测平台：{plat}")
    print(f"📋可用模型: {', '.join([f'{m}(→{get_model_name(m)})' for m in MODEL_LIST])}")
    print(f"💡输入 'model <名字>' 切换模型，如: model llama")
    print(f"💡输入 'new' 或 '新建对话' 清空对话，开始新对话")
    print(f"👋输入 quit 退出\n")

    while True:
        # 修复：捕获 EOF(Ctrl+D) 与 KeyboardInterrupt(Ctrl+C)，优雅退出
        try:
            q = input("👤我：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 已退出")
            break
        # 修复：空输入直接跳过，不发送空 user 消息给模型
        if not q:
            continue
        if q.lower() in ["quit", "exit"]:
            break
        if q.startswith("model "):
            new_model = q[6:].strip().lower()
            switch_model(new_model)
            continue
        # 修复：主循环全局异常兜底，任何 API/工具异常都不再导致进程崩溃退出
        try:
            agent_loop(q)
        except Exception as e:
            print(f"❌ 处理输入时发生异常: {e}，已跳过本轮，程序继续运行")
            continue
