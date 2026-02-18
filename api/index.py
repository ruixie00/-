# api/index.py - 终极增强版 (带锁 + 北京时间校准)
from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import APIKeyHeader
import os
import json
from datetime import datetime, timedelta, timezone # <--- 改动1: 引入时区处理
from webdav3.client import Client
import tempfile

app = FastAPI()

# ====== 1. 安全配置 ======
API_SECRET = os.environ.get("API_SECRET", "123456")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def check_auth(request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=403, detail="🔒 门锁紧闭：请出示 API 密钥")
    
    if auth.startswith("Bearer "):
        token = auth.split(" ")[1]
    else:
        token = auth
        
    if token != API_SECRET:
        raise HTTPException(status_code=403, detail="🚫 钥匙错误：无法进入")

# ====== 2. 坚果云连接 ======
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
VAULT_PATH = "/Ethan记忆库/AI_Memory"

def get_client():
    if not webdav_config['webdav_login']: return None
    return Client(webdav_config)

# ====== 3. 核心能力 (Write, Search, Read) ======
# (前面的函数保持不变)
def save_note(title, content):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        # 这里保存文件名时，也尽量用北京时间，防止文件名乱套
        beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
        timestamp = beijing_now.strftime("%Y-%m-%d_%H%M%S")
        
        safe_title = "".join([c for c in title if c.isalnum() or c in (' ','-','_')]).strip()
        filename = f"{timestamp}_{safe_title}.md"
        md = f"# {title}\n\n{content}\n\n---\nCreated: {beijing_now}"
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', suffix='.md') as t:
            t.write(md)
            tmp_path = t.name
        client.upload_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        os.remove(tmp_path)
        return f"✅ 记下来啦！文件是: {filename}"
    except Exception as e: return f"❌ 写入失败: {str(e)}"

def search_notes(keyword):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        files = client.list(VAULT_PATH)
        matched = [f for f in files if keyword in f and f.endswith('.md')]
        if not matched: return f"📭 没找到标题包含 '{keyword}' 的笔记。"
        return f"🔍 找到了 (前10个):\n" + "\n".join(matched[:10])
    except Exception as e: return f"❌ 搜索出错: {str(e)}"

def read_note(filename):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.md') as t:
            tmp_path = t.name
        client.download_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        with open(tmp_path, 'r', encoding='utf-8') as f: content = f.read()
        os.remove(tmp_path)
        return f"📄 【{filename}】内容:\n\n{content[:3000]}"
    except Exception as e: return f"❌ 读取失败: {str(e)}"

# ====== 4. 新增功能: 获取正确时间 ======
def get_current_status():
    # 获取 UTC 时间
    utc_now = datetime.now(timezone.utc)
    # 强制加 8 小时变成北京时间
    beijing_now = utc_now + timedelta(hours=8)
    
    # 格式化输出
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_str = weekdays[beijing_now.weekday()]
    time_str = beijing_now.strftime("%Y-%m-%d %H:%M:%S")
    
    return f"🕒 当前北京时间: {time_str} ({weekday_str})\n🌍 服务器时区: UTC+8 (已校准)"

# ====== 5. MCP 接口 ======
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    await check_auth(request)
    
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EthanSecureMemory", "version": "4.1"}
            }
        }
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "save_memory",
                        "description": "【写入】保存重要日记、对话或总结",
                        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]}
                    },
                    {
                        "name": "search_memory",
                        "description": "【搜索】根据关键词查找笔记文件名",
                        "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
                    },
                    {
                        "name": "read_memory",
                        "description": "【读取】读取某篇笔记的详细内容",
                        "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}
                    },
                    # 👇👇👇 新增的工具注册在这里 👇👇👇
                    {
                        "name": "get_world_time",
                        "description": "【时间】获取当前的北京时间和日期，用于判断是白天还是晚上",
                        "inputSchema": {"type": "object", "properties": {}, "required": []} 
                    }
                ]
            }
        }

    if method == "tools/call":
        params = data.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        res = "未知指令"
        if name == "save_memory": res = save_note(args.get("title"), args.get("content"))
        elif name == "search_memory": res = search_notes(args.get("keyword"))
        elif name == "read_memory": res = read_note(args.get("filename"))
        # 👇👇👇 新增的调用逻辑 👇👇👇
        elif name == "get_world_time": res = get_current_status()
            
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": res}]}}

    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

@app.get("/")
def home(): return {"status": "Secure Server Online 🔒 (Time Calibrated)"}