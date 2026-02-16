# api/index.py - 最终加密版 (带锁的完整大脑)
from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import APIKeyHeader
import os
import json
from datetime import datetime
from webdav3.client import Client
import tempfile

app = FastAPI()

# ====== 1. 安全配置 (新增的锁) ======
# 从 Vercel 环境变量里读取密码，如果没有设置，默认是 "123456" (为了防止报错)
API_SECRET = os.environ.get("API_SECRET", "123456")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def check_auth(request: Request):
    # 检查请求头里有没有钥匙
    auth = request.headers.get("Authorization")
    # 允许 Bearer Token 格式或者直接密码
    if not auth:
        raise HTTPException(status_code=403, detail="🔒 门锁紧闭：请出示 API 密钥")
    
    # 处理 "Bearer <key>" 格式
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
# (为了节省篇幅，这里复用之前的功能函数，逻辑不变)
def save_note(title, content):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_title = "".join([c for c in title if c.isalnum() or c in (' ','-','_')]).strip()
        filename = f"{timestamp}_{safe_title}.md"
        md = f"# {title}\n\n{content}\n\n---\nCreated: {datetime.now()}"
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

# ====== 4. MCP 接口 (这里加了锁！) ======
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    # 🛑 只有这一行是新增的：先检查钥匙，没有钥匙不准往下走
    await check_auth(request)
    
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    # (后面的握手、工具列表、调用逻辑全部保持不变)
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EthanSecureMemory", "version": "4.0"}
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
                    }
                ]
            }
        }

    if method == "tools/call":
        params = data.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        if name == "save_memory": res = save_note(args.get("title"), args.get("content"))
        elif name == "search_memory": res = search_notes(args.get("keyword"))
        elif name == "read_memory": res = read_note(args.get("filename"))
        else: res = "未知指令"
            
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": res}]}}

    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

@app.get("/")
def home(): return {"status": "Secure Server Online 🔒"}