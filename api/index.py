# api/index.py
from fastapi import FastAPI, Request
from pydantic import BaseModel
from datetime import datetime
import tempfile
from webdav3.client import Client
import os
import json

app = FastAPI()

# ====== 坚果云配置 ======
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
VAULT_PATH = "/Ethan记忆库/AI_Memory"

# ====== 核心功能：写笔记 ======
def save_note_to_nutstore(title, content):
    if not webdav_config['webdav_login']:
        return "❌ 错误：坚果云环境变量未配置"
    
    client = Client(webdav_config)
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_title = "".join([c for c in title if c.isalnum() or c in (' ','-','_')]).strip()
        filename = f"{timestamp}_{safe_title}.md"
        
        md_content = f"""---
created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
source: AI_Assistant
---

# {title}

{content}
"""
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', suffix='.md') as tmp:
            tmp.write(md_content)
            tmp_path = tmp.name

        remote_path = f"{VAULT_PATH}/{filename}"
        client.upload_sync(remote_path=remote_path, local_path=tmp_path)
        os.remove(tmp_path)
        return f"✅ 成功！笔记已保存到：{filename}"
    except Exception as e:
        return f"❌ 保存失败: {str(e)}"

# ====== 1. 原来的 API 接口 (保留) ======
class NoteRequest(BaseModel):
    title: str
    content: str

@app.get("/")
def home():
    return {"status": "Online", "mode": "MCP + API"}

@app.post("/write_note")
def api_write_note(note: NoteRequest):
    result = save_note_to_nutstore(note.title, note.content)
    return {"message": result}

# ====== 2. 新增：MCP 协议接口 (给 Kelivo 用) ======
@app.post("/mcp")
async def handle_mcp(request: Request):
    """
    这是一个迷你的 MCP 协议处理器。
    它能听懂 'initialize', 'tools/list', 'tools/call' 三种指令。
    """
    try:
        data = await request.json()
        method = data.get("method")
        msg_id = data.get("id")
        
        # 1. 握手 (Initialize)
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}  # 告诉它我有工具能力
                    },
                    "serverInfo": {
                        "name": "EthanMemoryButler",
                        "version": "1.0"
                    }
                }
            }
        
        # 2. 确认握手 (Initialized Notification)
        if method == "notifications/initialized":
            return None # 只需要默默接收

        # 3. 列出工具 (List Tools) - 告诉 Kelivo 我有什么本事
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [{
                        "name": "save_memory",
                        "description": "保存重要对话、日记或总结到坚果云/Obsidian记忆库。",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "笔记标题"},
                                "content": {"type": "string", "description": "笔记内容(Markdown)"}
                            },
                            "required": ["title", "content"]
                        }
                    }]
                }
            }

        # 4. 调用工具 (Call Tool) - 真正干活
        if method == "tools/call":
            params = data.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            
            if name == "save_memory":
                # 执行保存逻辑
                result_text = save_note_to_nutstore(args.get("title"), args.get("content"))
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}]
                    }
                }
            
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}}

    except Exception as e:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(e)}}