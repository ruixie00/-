from fastapi import FastAPI, Request
import os
import json
from datetime import datetime
from webdav3.client import Client
import tempfile

app = FastAPI()

# 1. 坚果云配置 (硬核检查)
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
VAULT_PATH = "/Ethan记忆库/AI_Memory"

# 2. 核心写入功能
def save_to_nutstore(title, content):
    if not webdav_config['webdav_login']: return "❌ 错误: 环境变量未配置"
    try:
        client = Client(webdav_config)
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
    except Exception as e:
        return f"❌ 失败: {str(e)}"

# 3. 根目录 (活着的证明)
@app.get("/")
def home():
    return {"status": "MCP Server Ready", "url": "/mcp"}

# 4. MCP 协议专用接口 (Kelivo 调用的就是这个！)
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    # 握手: 告诉 Kelivo 我是谁
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EthanMemory", "version": "1.0"}
            }
        }
    
    # 列表: 告诉 Kelivo 我有什么工具
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [{
                    "name": "save_memory",
                    "description": "保存重要信息到坚果云记忆库",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"}
                        },
                        "required": ["title", "content"]
                    }
                }]
            }
        }
        
    # 调用: 真正干活
    if method == "tools/call":
        params = data.get("params", {})
        if params.get("name") == "save_memory":
            args = params.get("arguments", {})
            res = save_to_nutstore(args.get("title", "无标题"), args.get("content", ""))
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": res}]}
            }
            
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}