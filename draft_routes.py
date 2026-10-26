"""
Роутер /drafts — черновики статей от агента (см. content_agent.py).
Доступен только admin.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db, ArticleDraft, User
from content_agent import generate_one_draft

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("")
async def list_drafts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(
        select(ArticleDraft).where(ArticleDraft.status == "new").order_by(ArticleDraft.created_at.desc())
    )
    drafts = result.scalars().all()
    return {
        "items": [
            {"id": d.id, "topic": d.topic, "content": d.content, "created_at": d.created_at.isoformat()}
            for d in drafts
        ]
    }


@router.post("/generate")
async def generate_draft_now(current_user: User = Depends(get_current_user)):
    """Сгенерировать внеочередной черновик — только admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    try:
        draft = await generate_one_draft()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка генерации: {e}")

    return {
        "id": draft.id, "topic": draft.topic, "content": draft.content,
        "created_at": draft.created_at.isoformat(),
    }


@router.post("/{draft_id}/archive")
async def archive_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(select(ArticleDraft).where(ArticleDraft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Черновик не найден")

    draft.status = "archived"
    await db.commit()
    return {"ok": True}
