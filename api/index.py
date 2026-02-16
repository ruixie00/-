# api/index.py - V2.0 (全能读写版)
from fastapi import FastAPI, Request
import os
import json
from datetime import datetime
from webdav3.client import Client
import tempfile

app = FastAPI()

# ====== 配置区域 ======
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

# ====== 核心能力 ======
# 1. 写笔记
def save_note(title, content):
    client = get_client()
    if not client: return "❌ 错误: 环境变量未配置"
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
        return f"✅ 记忆已保存: {filename}"
    except Exception as e: return f"❌ 保存失败: {str(e)}"

# 2. 搜笔记 (搜文件名)
def search_notes(keyword):
    client = get_client()
    if not client: return "❌ 错误: 环境变量未配置"
    try:
        # 获取文件列表
        files = client.list(VAULT_PATH)
        # 简单的关键词过滤
        matched = [f for f in files if keyword in f and f.endswith('.md')]
        if not matched: return "📭 没有找到相关笔记。"
        return "🔍 找到以下笔记:\n" + "\n".join(matched)
    except Exception as e: return f"❌ 搜索出错: {str(e)}"

# 3. 读笔记 (读取内容)
def read_note(filename):
    client = get_client()
    if not client: return "❌ 错误: 环境变量未配置"
    try:
        # Vercel 不支持直接下载到内存，必须用临时文件
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.md') as t:
            tmp_path = t.name
        
        remote_path = f"{VAULT_PATH}/{filename}"
        client.download_sync(remote_path=remote_path, local_path=tmp_path)
        
        with open(tmp_path, 'r', encoding='utf-8') as f:
            content = f.read()
        os.remove(tmp_path)
        return f"📄 笔记内容 ({filename}):\n\n{content}"
    except Exception as e: return f"❌ 读取失败: {str(e)}"

# ====== 接口 ======
@app.get("/")
def home(): return {"status": "Ethan Memory V2 Ready"}

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    # 1. 握手
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EthanMemory", "version": "2.0"}
            }
        }
    
    # 2. 列出工具 (告诉 Kelivo 我现在有三个本事！)
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "save_memory",
                        "description": "保存重要信息到坚果云",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["title", "content"]
                        }
                    },
                    {
                        "name": "search_memory",
                        "description": "搜索记忆库中的笔记文件名",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"keyword": {"type": "string", "description": "搜索关键词"}},
                            "required": ["keyword"]
                        }
                    },
                    {
                        "name": "read_memory",
                        "description": "读取某篇笔记的具体内容",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"filename": {"type": "string", "description": "要读取的完整文件名"}},
                            "required": ["filename"]
                        }
                    }
                ]
            }
        }

    # 3. 调用工具 (分配任务)
    if method == "tools/call":
        params = data.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        result_text = "未知指令"
        if name == "save_memory":
            result_text = save_note(args.get("title"), args.get("content"))
        elif name == "search_memory":
            result_text = search_notes(args.get("keyword"))
        elif name == "read_memory":
            result_text = read_note(args.get("filename"))
            
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": result_text}]}
        }

    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}