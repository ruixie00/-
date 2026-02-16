# api/index.py - 终极全能版 (听说读写一条龙)
from fastapi import FastAPI, Request
import os
import json
from datetime import datetime
from webdav3.client import Client
import tempfile

app = FastAPI()

# ====== 1. 坚果云连接配置 ======
# (不用动，只要Vercel环境变量配好了就行)
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
# 你的记忆库路径
VAULT_PATH = "/Ethan记忆库/AI_Memory"

def get_client():
    if not webdav_config['webdav_login']: return None
    return Client(webdav_config)

# ====== 2. 三大核心能力 (Write, Search, Read) ======

# [能力一] 写日记
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

# [能力二] 找东西 (搜文件名)
def search_notes(keyword):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        # 列出文件夹里所有文件
        files = client.list(VAULT_PATH)
        # 只要.md结尾的，且包含关键词的
        matched = [f for f in files if keyword in f and f.endswith('.md')]
        
        if not matched: 
            return f"📭 找了一圈，没发现标题里包含 '{keyword}' 的笔记。"
        
        # 最多返回前10个，防止太多刷屏
        result = "\n".join(matched[:10])
        return f"🔍 找到了这些笔记 (前10个):\n{result}\n\n(如果要看具体内容，请告诉我文件名)"
    except Exception as e: return f"❌ 搜索出错: {str(e)}"

# [能力三] 读内容 (读取具体文件)
def read_note(filename):
    client = get_client()
    if not client: return "❌ 错误: 没配置坚果云密码"
    try:
        # 下载到临时文件读取
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.md') as t:
            tmp_path = t.name
        
        # 尝试下载
        remote_path = f"{VAULT_PATH}/{filename}"
        client.download_sync(remote_path=remote_path, local_path=tmp_path)
        
        with open(tmp_path, 'r', encoding='utf-8') as f:
            content = f.read()
        os.remove(tmp_path)
        
        # 防止内容太长，截取前3000字
        if len(content) > 3000:
            content = content[:3000] + "\n...(后面太长了省略)..."
            
        return f"📄 【{filename}】的内容如下:\n\n{content}"
    except Exception as e: return f"❌ 读取失败: {str(e)} (可能是文件名不对？)"

# ====== 3. MCP 协议总管 (Kelivo 对接处) ======
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    # 握手
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EthanUltimateMemory", "version": "3.0"}
            }
        }
    
    # 列出工具 (告诉 Kelivo 我有三头六臂)
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "save_memory",
                        "description": "【写入】保存重要日记、对话或总结",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "笔记标题"},
                                "content": {"type": "string", "description": "笔记内容"}
                            },
                            "required": ["title", "content"]
                        }
                    },
                    {
                        "name": "search_memory",
                        "description": "【搜索】根据关键词查找笔记文件名",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string", "description": "搜索关键词"}
                            },
                            "required": ["keyword"]
                        }
                    },
                    {
                        "name": "read_memory",
                        "description": "【读取】读取某篇笔记的详细内容",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string", "description": "完整的文件名(从搜索结果中获取)"}
                            },
                            "required": ["filename"]
                        }
                    }
                ]
            }
        }

    # 执行工具
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