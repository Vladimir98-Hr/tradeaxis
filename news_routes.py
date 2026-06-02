"""
Роутер /news — публичная лента записей автора.
Добавлять/удалять посты может только admin.
Файлы сохраняются в uploads/news/.
"""

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db, NewsPost
from database import User

router = APIRouter(prefix="/news", tags=["news"])

UPLOAD_DIR = Path("uploads/news")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_FILES = 10

# Определяем тип файла по mime / расширению
def _media_type(filename: str, content_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if content_type.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return "image"
    if content_type.startswith("audio/") or ext in (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"):
        return "audio"
    return "doc"


@router.get("")
async def list_news(db: AsyncSession = Depends(get_db)):
    """Публичный эндпоинт — список постов (новые сначала)."""
    result = await db.execute(
        select(NewsPost).order_by(NewsPost.created_at.desc())
    )
    posts = result.scalars().all()
    out = []
    for p in posts:
        media = json.loads(p.media or "[]")
        # добавляем URL к каждому медиафайлу
        for m in media:
            m["url"] = f"/uploads/news/{m['filename']}"
        out.append({
            "id": p.id,
            "content": p.content,
            "media": media,
            "created_at": p.created_at.isoformat(),
        })
    return {"posts": out}


@router.post("")
async def create_news(
    content: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать пост — только admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_FILES} файлов")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    media = []
    for f in files:
        if not f.filename:
            continue
        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"Файл {f.filename} слишком большой (макс. 50 МБ)")
        ext = Path(f.filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOAD_DIR / unique_name
        dest.write_bytes(data)
        media.append({
            "type": _media_type(f.filename, f.content_type or ""),
            "filename": unique_name,
            "original_name": f.filename,
        })

    post = NewsPost(content=content, media=json.dumps(media, ensure_ascii=False))
    db.add(post)
    await db.commit()
    await db.refresh(post)

    media_out = json.loads(post.media)
    for m in media_out:
        m["url"] = f"/uploads/news/{m['filename']}"

    return {
        "id": post.id,
        "content": post.content,
        "media": media_out,
        "created_at": post.created_at.isoformat(),
    }


@router.delete("/{post_id}")
async def delete_news(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить пост — только admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(select(NewsPost).where(NewsPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")

    # Удаляем файлы с диска
    try:
        media = json.loads(post.media or "[]")
        for m in media:
            p = UPLOAD_DIR / m["filename"]
            if p.exists():
                p.unlink()
    except Exception:
        pass

    await db.delete(post)
    await db.commit()
    return {"ok": True}
