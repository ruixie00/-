# api/index.py - 智能记忆库（自然语言版）
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.security import APIKeyHeader
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
    version="6.1"
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

def safe_save_note(title: str, content: str) -> str:
    """安全的笔记保存（确保临时文件清理）"""
    client = create_webdav_client()
    tmp_path = None
    
    try:
        beijing_now = get_beijing_time()
        timestamp = beijing_now.strftime("%Y-%m-%d_%H%M%S")
        
        # 清理文件名（防止特殊字符）
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()
        if not safe_title:
            safe_title = "未命名笔记"
            
        filename = f"{timestamp}_每日总结.md"
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

def read_note_content_safe(client, filename: str, limit: int = 1000) -> str:
    """安全读取笔记内容"""
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
def natural_search_notes(keyword: str) -> str:
    """自然语言搜索：返回自然语言结果"""
    client = create_webdav_client()
    
    try:
        # 获取所有.md文件
        all_files = client.list(VAULT_PATH)
        md_files = [f for f in all_files if f.endswith('.md')]
        
        if not md_files:
            return f"我在你的记忆库里没有找到任何笔记文件，可能还没有开始记录呢。"
        
        # 搜索结果
        matched_files = []
        
        # 遍历每个文件，检查文件名和内容
        for filename in md_files:
            try:
                # 1. 检查文件名
                name_match = keyword.lower() in filename.lower()
                
                # 2. 检查文件内容（关键！）
                content_match = False
                content_preview = ""
                
                # 读取文件内容（只读前1000字符，提高速度）
                content = read_note_content_safe(client, filename, 1000)
                content_preview = content[:200]  # 预览200字符
                
                # 检查关键词是否在内容中
                if keyword.lower() in content.lower():
                    content_match = True
                
                # 如果文件名或内容匹配，就加入结果
                if name_match or content_match:
                    matched_files.append({
                        "filename": filename,
                        "name_match": name_match,
                        "content_match": content_match,
                        "preview": content_preview
                    })
                    
            except Exception as e:
                # 单个文件处理失败，继续下一个
                continue
        
        # 生成自然语言回复
        if not matched_files:
            return f"我在你的记忆库里搜索了『{keyword}』，但没有找到相关的笔记。可能你还没有记录过相关内容，或者换个关键词试试？"
        
        # 找到内容了，生成自然回复
        if len(matched_files) == 1:
            # 只有一个结果
            file_info = matched_files[0]
            filename = file_info["filename"]
            preview = file_info["preview"]
            
            # 提取日期
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
            date_str = date_match.group(1) if date_match else "某天"
            
            return f"我在你的记忆库里找到了关于『{keyword}』的记录，是在{date_str}的每日总结里。内容大概是：{preview}..."
        
        else:
            # 多个结果
            result = f"我在你的记忆库里找到了{len(matched_files)}篇关于『{keyword}』的笔记：\n\n"
            
            for i, file_info in enumerate(matched_files[:3], 1):
                filename = file_info["filename"]
                preview = file_info["preview"]
                
                # 提取日期
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
                date_str = date_match.group(1) if date_match else "某天"
                
                result += f"{i}. {date_str}的记录提到：{preview}...\n\n"
            
            if len(matched_files) > 3:
                result += f"还有{len(matched_files) - 3}篇相关记录，需要的话我可以帮你详细查看。"
            
            return result
        
    except Exception as e:
        return f"抱歉，搜索你的记忆库时遇到了问题：{str(e)}。请稍后再试。"

def safe_read_note(filename: str) -> str:
    """安全的笔记读取"""
    client = create_webdav_client()
    tmp_path = None
    
    try:
        # 验证文件名（防止路径遍历攻击）
        if not filename.endswith('.md') or '..' in filename or '/' in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="❌ 文件名不合法"
            )
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
            tmp_path = f.name
        
        # 下载文件
        remote_path = f"{VAULT_PATH}/{filename}"
        client.download_sync(remote_path=remote_path, local_path=tmp_path)
        
        # 读取内容
        with open(tmp_path, 'r', encoding='utf-8') as f:
            content = f.read(5000)  # 限制读取长度
        
        if len(content) >= 5000:
            content = content[:5000] + "\n\n... (内容过长，已截断)"
        
        # 提取日期
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        date_str = date_match.group(1) if date_match else "某天"
        
        return f"这是你{date_str}的笔记内容：\n\n{content}"
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"❌ 读取失败: {str(e)}"
        )
    finally:
        # 清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

# ====== 5. 智能功能 ======

# 初始化jieba
try:
    jieba.initialize()
except:
    pass

def smart_extract_keyword(message: str) -> str:
    """使用jieba分词智能提取关键词"""
    # 1. 清理消息
    clean_msg = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', message)
    
    # 2. 中文分词
    words = jieba.lcut(clean_msg)
    
    # 3. 过滤停用词
    stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    
    # 4. 提取关键词
    keywords = []
    for word in words:
        if (len(word) > 1 and 
            word not in stop_words and 
            not word.isdigit()):
            keywords.append(word)
    
    # 5. 返回最可能的关键词
    if keywords:
        return keywords[0]
    
    # 6. 备用方案：提取消息中的最长中文词
    chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,}', message)
    if chinese_words:
        return max(chinese_words, key=len)
    
    return ""

def detect_search_intent(message: str) -> bool:
    """智能检测是否需要搜索记忆库"""
    triggers = {
        '上次', '之前', '笔记', '记得', '学过', '写过', '记录',
        '查一下', '找找', '在哪里', '什么内容', '回忆', '想起',
        '之前说', '前些天', '上个月', '去年',
        'search', 'find', 'look for', 'where is', 'note', 'memory'
    }
    
    lower_msg = message.lower()
    
    # 检查是否包含触发词
    for trigger in triggers:
        if trigger in lower_msg:
            return True
    
    # 检查疑问模式
    question_patterns = [
        r'(.+)是什么',
        r'如何(.+)',
        r'(.+)怎么',
        r'(.+)在哪里',
        r'where is (.+)',
        r'how to (.+)'
    ]
    
    for pattern in question_patterns:
        if re.search(pattern, message):
            return True
    
    return False

# ====== 6. API端点 ======

@app.get("/")
async def root():
    """首页"""
    return {
        "status": "🚀 Ethan智能记忆库运行中",
        "version": "6.1",
        "features": ["安全鉴权", "智能搜索", "自然语言回复", "北京时间"],
        "endpoints": {
            "/health": "健康检查",
            "/api/time": "获取北京时间",
            "/api/smart_gateway": "智能记忆网关",
            "/mcp": "MCP协议接口"
        }
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": get_beijing_time().isoformat(),
        "service": "memory-butler"
    }

@app.get("/api/time")
async def get_time(authorized: bool = Depends(verify_api_key)):
    """获取北京时间"""
    beijing_now = get_beijing_time()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_str = weekdays[beijing_now.weekday()]
    
    return {
        "time": beijing_now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": weekday_str,
        "timestamp": beijing_now.timestamp(),
        "timezone": "UTC+8 (北京时间)"
    }

@app.post("/api/smart_gateway")
async def smart_gateway(
    request: SmartQueryRequest,
    authorized: bool = Depends(verify_api_key)
):
    """智能记忆网关（小姐姐同款功能）"""
    message = request.message
    
    # 1. 检测是否需要搜索
    if not detect_search_intent(message):
        return {
            "enhanced_message": message,
            "triggered": False,
            "reason": "未检测到搜索意图"
        }
    
    # 2. 提取关键词
    keyword = smart_extract_keyword(message)
    if not keyword:
        return {
            "enhanced_message": message,
            "triggered": False,
            "reason": "无法提取有效关键词"
        }
    
    # 3. 执行搜索（使用自然语言搜索）
    try:
        search_result = natural_search_notes(keyword)
        
        # 4. 生成增强提示
        enhanced_prompt = f"""
用户说："{message}"

【记忆助手提示】：
我刚刚在用户的记忆库中搜索了相关信息，这是我发现的内容：
{search_result}

请基于以上发现，自然地回答用户的问题。
就像你本来就记得这些内容一样，不要提到"搜索"或"查找"。
如果用户的问题和记忆内容相关，请结合记忆内容回答。
"""
        
        return {
            "enhanced_message": enhanced_prompt,
            "triggered": True,
            "keyword": keyword,
            "memory_summary": search_result[:100] + "..."
        }
        
    except HTTPException as e:
        # 搜索出错时，原样返回用户消息
        return {
            "enhanced_message": message,
            "triggered": False,
            "error": e.detail
        }

# ====== 7. MCP接口 ======
@app.post("/mcp")
async def mcp_endpoint(request: Request, authorized: bool = Depends(verify_api_key)):
    data = await request.json()
    method = data.get("method")
    msg_id = data.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "Ethan智能记忆库",
                    "version": "6.1",
                    "features": ["natural_language", "smart_search"]
                }
            }
        }
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "save_memory",
                        "description": "【写入】保存日记、笔记或对话",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"}
                            },
                            "required": ["title", "content"]
                        }
                    },
                    {
                        "name": "search_memory",
                        "description": "【搜索】智能搜索笔记（自然语言回复）",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string"}
                            },
                            "required": ["keyword"]
                        }
                    },
                    {
                        "name": "read_memory",
                        "description": "【读取】读取笔记详情",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"}
                            },
                            "required": ["filename"]
                        }
                    },
                    {
                        "name": "get_world_time",
                        "description": "【时间】获取北京时间",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "smart_query",
                        "description": "【智能助手】分析对话，自动查找相关记忆",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string"}
                            },
                            "required": ["message"]
                        }
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
                result = natural_search_notes(args.get("keyword", ""))
            elif name == "read_memory":
                result = safe_read_note(args.get("filename", ""))
            elif name == "get_world_time":
                beijing_now = get_beijing_time()
                result = f"🕒 现在是{beijing_now.strftime('%Y年%m月%d日 %H:%M:%S')}，{['周一','周二','周三','周四','周五','周六','周日'][beijing_now.weekday()]}"
            elif name == "smart_query":
                # 智能查询（直接返回自然语言结果）
                message = args.get("message", "")
                if detect_search_intent(message):
                    keyword = smart_extract_keyword(message)
                    if keyword:
                        result = natural_search_notes(keyword)
                    else:
                        result = "我没有从你的话中找到需要搜索的关键词。"
                else:
                    result = "当前对话不需要搜索记忆库。"
            else:
                result = f"未知工具: {name}"
            
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": result}]
                }
            }
            
        except HTTPException as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32000,
                    "message": e.detail
                }
            }
    
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

# ====== 8. 全局异常处理 ======
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一异常处理"""
    return {
        "error": True,
        "code": exc.status_code,
        "detail": exc.detail,
        "timestamp": get_beijing_time().isoformat()
    }