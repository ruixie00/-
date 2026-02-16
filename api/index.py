# api/index.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import tempfile
from webdav3.client import Client
import os
import urllib.parse

app = FastAPI()

# ====== 坚果云配置 (从环境变量读取，绝对安全) ======
webdav_config = {
    'webdav_hostname': os.environ.get('NUTSTORE_HOST', 'https://dav.jianguoyun.com/dav/'),
    'webdav_login': os.environ.get('NUTSTORE_EMAIL', ''),
    'webdav_password': os.environ.get('NUTSTORE_PASSWORD', ''),
    'disable_check': True
}

# 你的坚果云路径 (请确保坚果云里真的有这个文件夹，否则会报错)
# 建议：先在坚果云网页版里手动建好 "Ethan记忆库" 和里面的 "AI_Memory" 文件夹
VAULT_PATH = "/Ethan记忆库/AI_Memory"

class NoteRequest(BaseModel):
    title: str
    content: str

@app.get("/")
def home():
    return {"status": "Online", "message": "Ethan的云端记忆管家正在运行中..."}

@app.post("/write_note")
def write_note(note: NoteRequest):
    # 1. 检查配置
    if not webdav_config['webdav_login'] or not webdav_config['webdav_password']:
        return {"error": "云端环境变量未配置 (NUTSTORE_EMAIL / NUTSTORE_PASSWORD)"}

    client = Client(webdav_config)
    
    try:
        # 2. 准备文件名 (处理时间戳和标题)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # 简单过滤非法字符
        safe_title = "".join([c for c in note.title if c.isalnum() or c in (' ','-','_')]).strip()
        filename = f"{timestamp}_{safe_title}.md"
        
        # 3. 准备内容
        md_content = f"""---
created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
source: AI_Assistant
---

# {note.title}

{note.content}
"""
        
        # 4. 写入临时文件并上传
        # Vercel 是无服务器环境，只能用临时文件夹
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', suffix='.md') as tmp:
            tmp.write(md_content)
            tmp_path = tmp.name

        # 上传到坚果云 (使用 upload_sync)
        remote_file_path = f"{VAULT_PATH}/{filename}"
        client.upload_sync(remote_path=remote_file_path, local_path=tmp_path)
        
        # 删除临时文件
        os.remove(tmp_path)

        return {"success": True, "file": remote_file_path, "message": "记忆已归档"}

    except Exception as e:
        return {"success": False, "error": str(e)}