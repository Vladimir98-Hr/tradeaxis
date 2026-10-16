"""
Роутер /feedback — жалобы и предложения пользователей.
Отправлять может любой залогиненный пользователь, видеть список и
отмечать обработанными — только admin. Файлы (скриншоты) сохраняются
в uploads/feedback/.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db, Feedback, User

router = APIRouter(prefix="/feedback", tags=["feedback"])

UPLOAD_DIR = Path("uploads/feedback")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("")
async def create_feedback(
    message: str = Form(...),
    screenshot: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить жалобу/предложение — доступно любому залогиненному пользователю."""
    screenshot_path = None
    if screenshot is not None and screenshot.filename:
        if not (screenshot.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail="Скриншот должен быть изображением")
        data = await screenshot.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 5 МБ)")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(screenshot.filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / unique_name).write_bytes(data)
        screenshot_path = unique_name

    fb = Feedback(
        user_id=current_user.id,
        username=current_user.username,
        message=message,
        screenshot_path=screenshot_path,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    return {
        "id": fb.id,
        "message": fb.message,
        "screenshot_url": f"/uploads/feedback/{fb.screenshot_path}" if fb.screenshot_path else None,
        "status": fb.status,
        "created_at": fb.created_at.isoformat(),
    }


@router.get("")
async def list_feedback(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список обращений — только admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    query = select(Feedback).order_by(Feedback.created_at.desc())
    if status:
        query = query.where(Feedback.status == status)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": f.id,
                "user_id": f.user_id,
                "username": f.username,
                "message": f.message,
                "screenshot_url": f"/uploads/feedback/{f.screenshot_path}" if f.screenshot_path else None,
                "status": f.status,
                "created_at": f.created_at.isoformat(),
            }
            for f in items
        ]
    }


@router.post("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отметить обращение обработанным — только admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    fb.status = "resolved"
    await db.commit()
    return {"ok": True}
