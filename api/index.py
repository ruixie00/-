# api/index.py - 智能记忆库（V6.6 终极大一统护甲版）
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import os
import json
import re
from datetime import datetime, timedelta, timezone
from webdav3.client import Client
import tempfile
import jieba
from functools import lru_cache

app = FastAPI(title="Ethan智能记忆库", description="24小时在线的个人AI记忆管家", version="6.6")

# ====== 1. 安全鉴权 ======
API_SECRET = os.environ.get("API_SECRET", "123456")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def verify_api_key(auth_header: str = Depends(api_key_header)):
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="🔒 请提供API密钥")
    # 智能剥离 Bearer，管它带不带都能认出来
    token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else auth_header
    if not token or token != API_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="🚫 API密钥错误或已过期")
    return True

# ====== 2. 坚果云连接与核心功能 ======
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
VAULT_PATH = "/Ethan记忆库/AI_Memory"

def create_webdav_client():
    if not webdav_config['webdav_login']:
        raise HTTPException(status_code=500, detail="❌ 服务器未配置坚果云凭证")
    return Client(webdav_config)

def get_beijing_time():
    return datetime.now(timezone.utc) + timedelta(hours=8)

def safe_save_note(title: str, content: str) -> str:
    client = create_webdav_client()
    tmp_path = None
    try:
        beijing_now = get_beijing_time()
        safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', title).strip()
        filename = f"{beijing_now.strftime('%Y%m%d')}_{safe_title}.md" if safe_title else f"{beijing_now.strftime('%Y%m%d')}【每日总结】.md"
        md_content = f"# {title}\n\n{content}\n\n---\n📅 创建时间: {beijing_now.strftime('%Y年%m月%d日 %H:%M:%S')}\n📍 存储位置: {VAULT_PATH}/{filename}\n"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.md') as f:
            f.write(md_content)
            tmp_path = f.name
        client.upload_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        return f"✅ 笔记已保存！\n📁 文件名: {filename}\n📅 时间: {beijing_now.strftime('%H:%M')}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ 保存失败: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)

def read_note_content_safe(client, filename: str, limit: int = 3000) -> str:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as tmp:
            tmp_path = tmp.name
        client.download_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        with open(tmp_path, 'r', encoding='utf-8') as f:
            return f.read(limit)
    except: return "读取失败"
    finally:
        if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)

@lru_cache(maxsize=128)
def enhanced_natural_search_notes(keyword: str) -> str:
    client = create_webdav_client()
    try:
        all_files = client.list(VAULT_PATH)
        md_files = [f for f in all_files if f.endswith('.md')]
        if not md_files: return "记忆库里空空的哦。"
        
        matched_results = []
        kw = keyword.lower()
        for filename in md_files:
            if kw in filename.lower():
                matched_results.append(f"📄 标题匹配: {filename}")
                continue
            content = read_note_content_safe(client, filename, 800)
            if kw in content.lower():
                matched_results.append(f"📄 内容命中: {filename}\n预览: {content[:150]}...")
        
        if not matched_results: return f"没找到关于『{keyword}』的笔记。"
        return "我找到了这些记忆：\n\n" + "\n\n".join(matched_results[:3])
    except Exception as e:
        return f"搜索出错了: {str(e)}"

# ====== 3. MCP 接口 (恢复所有工具) ======
@app.post("/mcp")
async def mcp_endpoint(request: Request, authorized: bool = Depends(verify_api_key)):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "Ethan记忆库", "version": "6.6"}}}
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {"name": "save_memory", "description": "保存笔记", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]}},
                    {"name": "search_memory", "description": "搜索笔记", "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}},
                    {"name": "get_world_time", "description": "获取北京时间", "inputSchema": {"type": "object", "properties": {}}}
                ]
            }
        }

    if method == "tools/call":
        params = data.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        try:
            if name == "save_memory":
                result = safe_save_note(args.get("title", ""), args.get("content", ""))
            elif name == "search_memory":
                result = enhanced_natural_search_notes(args.get("keyword", ""))
            elif name == "get_world_time":
                beijing_now = get_beijing_time()
                result = f"🕒 现在是{beijing_now.strftime('%Y年%m月%d日 %H:%M:%S')}，星期{beijing_now.weekday() + 1}"
            else:
                result = f"未知工具: {name}"
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": result}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": f"🔧 工具执行遇到状况: {str(e)}"}]}}
    
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

# ====== 4. 全局异常处理（彻底消灭 500 报错） ======
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "code": exc.status_code, "detail": exc.detail, "timestamp": get_beijing_time().isoformat()}
    )
