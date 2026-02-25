# api/index.py - 智能记忆库（V6.5 终极修复版 - 解决 500 错误与鉴权异常）
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse  # 🚀 必须引入这个，解决“杀手1”
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

app = FastAPI(
    title="Ethan智能记忆库",
    description="24小时在线的个人AI记忆管家",
    version="6.5"
)

# ====== 1. 安全鉴权 ======
# 🚀 确认环境变量名：API_SECRET
API_SECRET = os.environ.get("API_SECRET", "123456")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def verify_api_key(auth_header: str = Depends(api_key_header)):
    """统一鉴权：支持Bearer token和直接token"""
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="🔒 请提供API密钥"
        )
    
    # 提取token（兼容两种格式）
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = auth_header
    
    if not token or token != API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="🚫 API密钥错误或已过期"
        )
    return True

# ====== 2. 数据模型定义 ======
class SaveNoteRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)

class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=50)

class SmartQueryRequest(BaseModel):
    message: str = Field(..., min_length=1)

# ====== 3. 坚果云连接 ======
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

# ====== 4. 核心功能函数 ======
def get_beijing_time():
    return datetime.now(timezone.utc) + timedelta(hours=8)

def read_note_content_safe(client, filename: str, limit: int = 3000) -> str:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as tmp:
            tmp_path = tmp.name
        client.download_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        with open(tmp_path, 'r', encoding='utf-8') as f:
            return f.read(limit)
    except:
        return "读取失败"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

@lru_cache(maxsize=128)
def enhanced_natural_search_notes(keyword: str) -> str:
    client = create_webdav_client()
    try:
        all_files = client.list(VAULT_PATH)
        md_files = [f for f in all_files if f.endswith('.md')]
        if not md_files: return "记忆库是空的哦。"
        
        matched_results = []
        kw = keyword.lower()
        for filename in md_files:
            if kw in filename.lower():
                matched_results.append(f"📄 标题匹配: {filename}")
                continue
            content = read_note_content_safe(client, filename, 500)
            if kw in content.lower():
                matched_results.append(f"📄 内容命中: {filename}\n预览: {content[:100]}...")
        
        if not matched_results:
            return f"没找到关于『{keyword}』的笔记。"
        return "\n\n".join(matched_results[:3])
    except Exception as e:
        return f"搜索出错了: {str(e)}"

# ====== 5. API端点 ======
@app.get("/")
async def root():
    return {"status": "🚀 Ethan记忆库运行中", "version": "6.5"}

@app.post("/mcp")
async def mcp_endpoint(request: Request, authorized: bool = Depends(verify_api_key)):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "Ethan记忆库", "version": "6.5"}}}
    
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [{"name": "search_memory", "description": "搜索笔记", "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}}]}}

    if method == "tools/call":
        params = data.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        if name == "search_memory":
            result = enhanced_natural_search_notes(args.get("keyword", ""))
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": result}]}}
    
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

# ====== 6. 全局异常处理（彻底修复杀手1） ======
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # 🚀 重点：必须使用 JSONResponse 包装，否则会报 500 TypeError
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True, 
            "code": exc.status_code, 
            "detail": exc.detail, 
            "timestamp": get_beijing_time().isoformat()
        }
    )
