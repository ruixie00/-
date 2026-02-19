# api/index.py - 智能记忆库（V6.4 修复版 - 文件名格式+搜索增强）
from fastapi import FastAPI, Request, HTTPException, Depends, status
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
    version="6.4"
)

# ====== 1. 安全鉴权 ======
API_SECRET = os.environ.get("API_SECRET", "123456")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def verify_api_key(auth_header: str = Depends(api_key_header)):
    """统一鉴权：支持Bearer token和直接token"""
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="🔒 请提供API密钥（格式：Bearer your_token 或直接your_token）"
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
    title: str = Field(..., min_length=1, max_length=200, description="笔记标题")
    content: str = Field(..., min_length=1, description="笔记内容")

class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=50, description="搜索关键词")

class SmartQueryRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户说的话")

# ====== 3. 坚果云连接 ======
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}
VAULT_PATH = "/Ethan记忆库/AI_Memory"

def create_webdav_client():
    """创建新的WebDAV客户端（线程安全）"""
    if not webdav_config['webdav_login']:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="❌ 服务器未配置坚果云凭证"
        )
    return Client(webdav_config)

# ====== 4. 核心功能 ======

def get_beijing_time():
    """获取北京时间（确保一致性）"""
    return datetime.now(timezone.utc) + timedelta(hours=8)

def get_simple_filename():
    """【V6.4 修复 1：简化文件名格式】生成 20260218【每日总结】.md 格式"""
    beijing_now = get_beijing_time()
    return f"{beijing_now.strftime('%Y%m%d')}【每日总结】.md"

def safe_save_note(title: str, content: str) -> str:
    """安全的笔记保存（确保临时文件清理）"""
    client = create_webdav_client()
    tmp_path = None
    
    try:
        beijing_now = get_beijing_time()
        
        # 清理文件名（防止特殊字符） - 【修复1：保留中文】
        safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', title).strip()
        
        # 【V6.4 修复：避免覆盖，基于标题生成文件名】
        if safe_title:
            # 使用"日期_标题.md"格式，避免覆盖
            filename = f"{beijing_now.strftime('%Y%m%d')}_{safe_title}.md"
        else:
            # 如果标题清理后为空，回退到原格式
            filename = get_simple_filename()
            
        md_content = f"""# {title}

{content}

---
📅 创建时间: {beijing_now.strftime('%Y年%m月%d日 %H:%M:%S')}
📍 存储位置: {VAULT_PATH}/{filename}
"""
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.md') as f:
            f.write(md_content)
            tmp_path = f.name
        
        # 上传到坚果云
        remote_path = f"{VAULT_PATH}/{filename}"
        client.upload_sync(remote_path=remote_path, local_path=tmp_path)
        
        return f"✅ 笔记已保存！\n📁 文件名: {filename}\n📅 时间: {beijing_now.strftime('%H:%M')}"
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"❌ 保存失败: {str(e)}"
        )
    finally:
        # 确保清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

def read_note_content_safe(client, filename: str, limit: int = 3000) -> str:
    """安全读取笔记内容（容量提升至3000字）"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as tmp:
            tmp_path = tmp.name
        
        client.download_sync(remote_path=f"{VAULT_PATH}/{filename}", local_path=tmp_path)
        
        with open(tmp_path, 'r', encoding='utf-8') as f:
            return f.read(limit)
            
    except Exception as e:
        return f"读取失败: {str(e)}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

@lru_cache(maxsize=128)
def enhanced_natural_search_notes(keyword: str) -> str:
    """【V6.4 修复 2：增强搜索功能】自然语言搜索：更好的匹配算法"""
    client = create_webdav_client()
    
    try:
        # 获取所有.md文件
        all_files = client.list(VAULT_PATH)
        md_files = [f for f in all_files if f.endswith('.md')]
        
        if not md_files:
            return f"我在你的记忆库里没有找到任何笔记文件，可能还没有开始记录呢。"
        
        # 搜索结果
        matched_files = []
        keyword_lower = keyword.lower()
        
        # 遍历每个文件，检查文件名和内容
        for filename in md_files:
            try:
                # 1. 检查文件名（新的格式匹配）
                name_match = keyword_lower in filename.lower()
                
                # 2. 检查文件内容（增强匹配算法）
                content_match = False
                content_preview = ""
                match_details = []
                
                # 读取文件内容
                content = read_note_content_safe(client, filename, 3000)
                content_lower = content.lower()
                content_preview = content[:200]  # 预览200字符
                
                # 【V6.4 增强匹配算法】
                
                # 精确匹配
                if keyword_lower in content_lower:
                    content_match = True
                    match_details.append("精确匹配")
                
                # 包含匹配：检查关键词是否被内容包含
                if not content_match and len(keyword) >= 2:
                    content_words = content_lower.split()
                    for word in content_words:
                        if keyword_lower in word or word in keyword_lower:
                            content_match = True
                            match_details.append("包含匹配")
                            break
                
                # 字符匹配：检查关键词的所有字符是否都在内容中
                if not content_match and len(keyword) >= 2:
                    keyword_chars = set(keyword_lower)
                    content_chars = set(content_lower)
                    if keyword_chars.issubset(content_chars):
                        content_match = True
                        match_details.append("字符匹配")
                
                # 如果文件名或内容匹配，就加入结果
                if name_match or content_match:
                    matched_files.append({
                        "filename": filename,
                        "name_match": name_match,
                        "content_match": content_match,
                        "preview": content_preview,
                        "match_details": match_details
                    })
                    
            except Exception as e:
                # 单个文件处理失败，继续下一个
                continue
        
        # 生成自然语言回复
        if not matched_files:
            return f"我在你的记忆库里搜索了『{keyword}』，但没有找到相关的笔记。可能你还没有记录过相关内容，或者换个关键词试试？"
        
        # 找到内容了，生成自然回复
        if len(matched_files) == 1:
            file_info = matched_files[0]
            filename = file_info["filename"]
            preview = file_info["preview"]
            
            # 【V6.4 修复：更好的日期提取】
            date_match = re.search(r'(\d{8})', filename)
            date_str = date_match.group(1) if date_match else "某天"
            if len(date_str) == 8:
                formatted_date = f"{date_str[:4]}年{date_str[4:6]}月{date_str[6:8]}日"
            else:
                formatted_date = date_str
            
            match_type = ""
            if file_info["name_match"] and file_info["content_match"]:
                match_type = "文件名和内容都"
            elif file_info["name_match"]:
                match_type = "文件名"
            else:
                match_type = "内容"
            
            return f"我在你的记忆库里找到了关于『{keyword}』的记录，是在{formatted_date}的每日总结里（{match_type}匹配）。内容大概是：{preview}..."
        
        else:
            result = f"我在你的记忆库里找到了{len(matched_files)}篇关于『{keyword}』的笔记：\n\n"
            for i, file_info in enumerate(matched_files[:3], 1):
                filename = file_info["filename"]
                preview = file_info["preview"]
                
                date_match = re.search(r'(\d{8})', filename)
                date_str = date_match.group(1) if date_match else "某天"
                if len(date_str) == 8:
                    formatted_date = f"{date_str[:4]}年{date_str[4:6]}月{date_str[6:8]}日"
                else:
                    formatted_date = date_str
                
                match_type = ""
                if file_info["name_match"] and file_info["content_match"]:
                    match_type = "文件名和内容"
                elif file_info["name_match"]:
                    match_type = "文件名"
                else:
                    match_type = "内容"
                
                result += f"{i}. {formatted_date}的记录（{match_type}匹配）提到：{preview}...\n\n"
            
            if len(matched_files) > 3:
                result += f"还有{len(matched_files) - 3}篇相关记录，需要的话我可以帮你详细查看。"
            
            return result
        
    except Exception as e:
        return f"抱歉，搜索你的记忆库时遇到了问题：{str(e)}。请稍后再试。"

def safe_read_note(filename: str) -> str:
    """安全的笔记读取"""
    # 【V6.3 修复 1：AI如果忘了后缀，自动补全】
    if not filename.endswith('.md'):
        filename += '.md'
        
    client = create_webdav_client()
    tmp_path = None
    
    try:
        if '..' in filename or '/' in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="❌ 文件名不合法"
            )
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
            tmp_path = f.name
        
        remote_path = f"{VAULT_PATH}/{filename}"
        client.download_sync(remote_path=remote_path, local_path=tmp_path)
        
        with open(tmp_path, 'r', encoding='utf-8') as f:
            content = f.read(5000)
        
        if len(content) >= 5000:
            content = content[:5000] + "\n\n... (内容过长，已截断)"
        
        # 【V6.4 修复：更好的日期提取】
        date_match = re.search(r'(\d{8})', filename)
        date_str = date_match.group(1) if date_match else "某天"
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}年{date_str[4:6]}月{date_str[6:8]}日"
        else:
            formatted_date = date_str
        
        return f"这是你{formatted_date}的笔记内容：\n\n{content}"
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"❌ 读取失败: {str(e)}"
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

# ====== 5. 智能功能 ======
try:
    jieba.initialize()
except:
    pass

def smart_extract_keyword(message: str) -> str:
    clean_msg = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', message)
    words = jieba.lcut(clean_msg)
    stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    
    keywords = []
    for word in words:
        if (len(word) > 1 and word not in stop_words and not word.isdigit()):
            keywords.append(word)
    
    if keywords:
        return keywords[0]
    
    chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,}', message)
    if chinese_words:
        return max(chinese_words, key=len)
    
    return ""

def detect_search_intent(message: str) -> bool:
    triggers = {
        '上次', '之前', '笔记', '记得', '学过', '写过', '记录',
        '查一下', '找找', '在哪里', '什么内容', '回忆', '想起',
        '之前说', '前些天', '上个月', '去年',
        'search', 'find', 'look for', 'where is', 'note', 'memory'
    }
    lower_msg = message.lower()
    for trigger in triggers:
        if trigger in lower_msg:
            return True
            
    question_patterns = [
        r'(.+)是什么', r'如何(.+)', r'(.+)怎么', r'(.+)在哪里',
        r'where is (.+)', r'how to (.+)'
    ]
    for pattern in question_patterns:
        if re.search(pattern, message):
            return True
    return False

# ====== 6. API端点 ======
@app.get("/")
async def root():
    return {
        "status": "🚀 Ethan智能记忆库运行中",
        "version": "6.4",
        "features": ["安全鉴权", "智能搜索", "自然语言回复", "北京时间", "文件名修复", "搜索增强"]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": get_beijing_time().isoformat()}

@app.get("/api/time")
async def get_time(authorized: bool = Depends(verify_api_key)):
    beijing_now = get_beijing_time()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return {
        "time": beijing_now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": weekdays[beijing_now.weekday()],
        "timezone": "UTC+8 (北京时间)"
    }

@app.post("/api/smart_gateway")
async def smart_gateway(request: SmartQueryRequest, authorized: bool = Depends(verify_api_key)):
    message = request.message
    if not detect_search_intent(message):
        return {"enhanced_message": message, "triggered": False}
        
    keyword = smart_extract_keyword(message)
    if not keyword:
        return {"enhanced_message": message, "triggered": False}
        
    try:
        # 【V6.4 修复：使用增强版搜索】
        search_result = enhanced_natural_search_notes(keyword)
        enhanced_prompt = f"""用户说："{message}"\n\n【记忆助手提示】：\n我刚刚在用户的记忆库中搜索了相关信息，这是我发现的内容：\n{search_result}\n\n请基于以上发现，自然地回答用户的问题。就像你本来就记得这些内容一样，不要提到"搜索"或"查找"。如果用户的问题和记忆内容相关，请结合记忆内容回答。"""
        return {"enhanced_message": enhanced_prompt, "triggered": True, "keyword": keyword}
    except HTTPException as e:
        return {"enhanced_message": message, "triggered": False, "error": e.detail}

# ====== 7. MCP接口 ======
@app.post("/mcp")
async def mcp_endpoint(request: Request, authorized: bool = Depends(verify_api_key)):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Ethan智能记忆库", "version": "6.4"}
            }
        }
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "save_memory",
                        "description": "【写入】保存日记、笔记或对话",
                        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]}
                    },
                    {
                        "name": "search_memory",
                        "description": "【搜索】智能搜索笔记（自然语言回复）",
                        "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
                    },
                    {
                        "name": "read_memory",
                        "description": "【读取】读取笔记详情",
                        "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}
                    },
                    {
                        "name": "get_world_time",
                        "description": "【时间】获取北京时间",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "smart_query",
                        "description": "【智能助手】分析对话，自动查找相关记忆",
                        "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
                    }
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
                # 【V6.4 修复：使用增强版搜索】
                result = enhanced_natural_search_notes(args.get("keyword", ""))
            elif name == "read_memory":
                result = safe_read_note(args.get("filename", ""))
            elif name == "get_world_time":
                beijing_now = get_beijing_time()
                result = f"🕒 现在是{beijing_now.strftime('%Y年%m月%d日 %H:%M:%S')}，{['周一','周二','周三','周四','周五','周六','周日'][beijing_now.weekday()]}"
            
            elif name == "smart_query":
                # 【V6.4 修复：使用增强版搜索】
                message = args.get("message", "")
                keyword = smart_extract_keyword(message)
                
                # 提不出关键词就直接用原话搜，强行喂给增强版检索引擎！
                search_term = keyword if keyword else message
                result = enhanced_natural_search_notes(search_term)
                
            else:
                result = f"未知工具: {name}"
            
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": result}]}}
            
        except HTTPException as e:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": e.detail}}
        except Exception as e:
            # 【V6.3 修复 2：拦截底层异常，转为文字反馈，防止 Kelivo 弹未知错误】
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": f"🔧 工具执行时遇到小状况: {str(e)}。可能文件不存在，请换个词试试。"}]}}
    
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

# ====== 8. 全局异常处理 ======
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return {"error": True, "code": exc.status_code, "detail": exc.detail, "timestamp": get_beijing_time().isoformat()}