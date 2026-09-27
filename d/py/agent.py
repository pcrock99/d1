# agent.py 跨平台简易Agent
import os
import json
import platform
import sqlite3
import time
from datetime import datetime, timedelta
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# ===================== 配置区 =====================
API_KEY = os.getenv("AGNES_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://apihub.agnes-ai.com/v1")

LOCAL_BASE_URL = os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "ollama")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "llama")

MAX_TURNS = 45
MAX_TURNS_COMPRESS_THRESHOLD = 25  # 达到此轮数时触发上下文压缩（兜底）
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
    cursor = conn.execute(
        "SELECT id, title, content, tags, created_at FROM memories WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
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
        keyword = user_query.strip()[:10] if user_query else ""
        if not keyword:
            return ""
        result = query_memory(keyword)
        if "📚 找到" in result:
            return f"\n【相关记忆】\n{result}"
    except Exception as e:
        print(f"⚠️ build_system_context 错误: {e}")
    return ""

# ================================================

MODEL_LIST = ["agnes-2.5-flash", "llama"]
current_model = "agnes-2.5-flash"

def get_client(model_name):
    if model_name == "llama":
        return OpenAI(api_key=LOCAL_API_KEY, base_url=LOCAL_BASE_URL)
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)

def get_model_name(model_name):
    if model_name == "llama":
        return LOCAL_MODEL
    return "agnes-2.5-flash"

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

# ===================== 对话状态 =====================
current_messages = None
current_turn_count = 0

def new_conversation():
    global current_messages, current_turn_count
    current_messages = None
    current_turn_count = 0
    return "🆕 已创建新对话，上下文已清空"

def reset_context(user_query: str, messages: list) -> tuple[list, int]:
    """压缩上下文：用 LLM 摘要历史对话，存入临时记忆，返回新的 messages 列表和重置后的轮次"""
    print("\n📦 上下文过长，正在压缩历史对话...")
    
    # 保留原始Agent系统提示词
    original_system = None
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            original_system = msg.get("content", "")
            break
    
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
            # 过滤掉 recent 中的 system 消息，避免发送多个 system
            recent = [m for m in (messages[-20:] if len(messages) > 20 else messages)
                      if not (isinstance(m, dict) and m.get("role") == "system")]
            resp = client.chat.completions.create(
                model=get_model_name(current_model),
                messages=[sys_msg] + recent,
                temperature=0.1
            )
            summary = resp.choices[0].message.content.strip()
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
                        recent = messages[-20:] if len(messages) > 20 else messages
                        resp = client.chat.completions.create(
                            model=get_model_name(current_model),
                            messages=[sys_msg] + recent,
                            temperature=0.1
                        )
                        summary = resp.choices[0].message.content.strip()
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

    print(f"✅ 上下文已压缩，摘要长度: {len(summary)} 字")
    save_memory(f"对话摘要 {datetime.now().strftime('%H:%M')}", summary, "temp_context")

    # 保留原始系统提示词
    new_system_content = original_system if original_system else (
        "你是本机终端智能助手，可以使用提供的工具完成用户任务。"
    )
    
    new_messages = [
        {
            "role": "system",
            "content": (
                f"{new_system_content}\n\n"
                "以下是之前的对话摘要，请基于它继续帮助用户：\n"
                f"{summary}\n\n"
                "原始问题："
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
    
    try:
        if IS_WIN:
            proc = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, timeout=120)
        else:
            proc = subprocess.run(cmd, shell=True, executable=os.environ.get("SHELL", "/bin/sh"), capture_output=True, text=True, timeout=120)
        
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
    
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
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
    
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
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
        summary = result[:100] + "..." if len(result) > 100 else result
        conn.execute(
            "INSERT INTO tool_log (timestamp, tool_name, args, result_summary) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tool_name, json.dumps(args, ensure_ascii=False), summary)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 工具日志记录失败: {e}")

def agent_loop(user_query: str):
    global current_messages, current_turn_count

    # 每轮用户输入时先增加轮次计数（区分对话轮次和工具调用轮次）
    current_turn_count += 1
    turn_count = current_turn_count

    # 新建对话指令
    if user_query.strip() in ["新建对话", "new", "new对话", "新对话", "清空对话"]:
        current_messages = None
        current_turn_count = 0
        print("🆕 已创建新对话，上下文已清空")
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

    turn_count = current_turn_count if current_turn_count is not None else 0
    
    # 计算总token数（用于触发压缩）
    total_tokens = sum(
        count_tokens_approx(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or "")
        for m in messages
    )

    for _ in range(MAX_TURNS):
        # 检查累计轮次是否已超限
        if turn_count >= MAX_TURNS:
            print(f"\n⚠️ 已达最大轮次 {MAX_TURNS}，停止")
            break
        # 检测是否接近上限，触发上下文压缩（以token为主，轮数为兜底）
        if (total_tokens > 12000 or turn_count >= MAX_TURNS_COMPRESS_THRESHOLD) and turn_count < MAX_TURNS:
            new_messages, new_turn = reset_context(user_query, messages)
            if new_messages is messages and new_turn == 0:
                # 压缩失败，保持原有轮次计数，避免轮次统计丢失
                print("⚠️ 上下文压缩失败，本轮跳过压缩")
                pass
            else:
                messages, turn_count = new_messages, new_turn
                actual_model = get_model_name(current_model)
                total_tokens = sum(
                    count_tokens_approx(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or "")
                    for m in messages
                )
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
                    return
                if retry_count > max_retries:
                    print(f"❌ API 限流，已重试 {max_retries} 次，跳过本轮对话")
                    return
                wait_time = min(2 ** retry_count, 10)
                print(f"⚠️ API 限流，等待 {wait_time} 秒后重试 ({retry_count}/{max_retries})...")
                time.sleep(wait_time)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            print(f"\n🤖Agent:\n{msg.content}")
            # 保存当前对话状态
            current_messages = messages
            current_turn_count = turn_count
            return
        messages.append(msg.model_dump() if hasattr(msg, "model_dump") else msg.dict())
        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            if fname not in tool_map:
                res = f"error: 未知工具 {fname}"
                args = {}
            else:
                print(f"\n🔧调用工具 {fname} → {args}")
                try:
                    res = tool_map[fname](**args)
                except Exception as e:
                    res = f"error: 工具执行异常 {e}"
            # 记录工具调用日志
            log_tool_call(fname, args, res)
            # 截断tool输出并警告
            if len(res) > 12000:
                res = res[:12000] + "\n... [工具输出已截断，超过12000字符]"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": res
            })
        turn_count += 1
        # 更新token计数
        total_tokens = sum(
            count_tokens_approx(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or "")
            for m in messages
        )
    
    print(f"\n⚠️已到达最大轮次 {MAX_TURNS}，自动停止。")
    # 保存当前对话状态
    current_messages = messages
    current_turn_count = turn_count

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
        q = input("👤我：").strip()
        if q.lower() in ["quit", "exit"]:
            break
        if q.startswith("model "):
            new_model = q[6:].strip().lower()
            switch_model(new_model)
            continue
        agent_loop(q)