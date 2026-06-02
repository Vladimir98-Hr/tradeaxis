"""
Роутер пользовательских данных: настройки, вотчлист, журнал сделок.
Все endpoints требуют авторизации.
"""

import json
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional

from database import User, UserSettings, WatchlistItem, TradeJournal, get_db
from auth import get_current_user

router = APIRouter(prefix="/user", tags=["user"])


# --- Схемы ---

class SettingsBody(BaseModel):
    settings: dict


class WatchlistItemSchema(BaseModel):
    symbol: str
    market: str = "crypto"
    position: int = 0


class WatchlistBody(BaseModel):
    items: List[WatchlistItemSchema]


class TradeBody(BaseModel):
    data: dict


class TradeResponse(BaseModel):
    id: int
    data: dict
    created_at: str

    class Config:
        from_attributes = True


# --- Settings ---

@router.get("/settings")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает сохранённые настройки пользователя."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings_row = result.scalar_one_or_none()
    if not settings_row:
        return {"settings": {}}
    return {"settings": json.loads(settings_row.settings_json)}


@router.put("/settings")
async def save_settings(
    body: SettingsBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохраняет настройки пользователя (upsert)."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row:
        settings_row.settings_json = json.dumps(body.settings, ensure_ascii=False)
    else:
        settings_row = UserSettings(
            user_id=current_user.id,
            settings_json=json.dumps(body.settings, ensure_ascii=False),
        )
        db.add(settings_row)

    await db.commit()
    return {"ok": True}


# --- Watchlist ---

@router.get("/watchlist")
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает вотчлист пользователя, отсортированный по position."""
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == current_user.id)
        .order_by(WatchlistItem.position)
    )
    items = result.scalars().all()
    return {"items": [{"symbol": i.symbol, "market": i.market, "position": i.position} for i in items]}


@router.put("/watchlist")
async def save_watchlist(
    body: WatchlistBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полностью перезаписывает вотчлист пользователя."""
    # Удаляем старые записи
    await db.execute(delete(WatchlistItem).where(WatchlistItem.user_id == current_user.id))

    # Добавляем новые
    for i, item in enumerate(body.items):
        db.add(WatchlistItem(
            user_id=current_user.id,
            symbol=item.symbol,
            market=item.market,
            position=i,
        ))

    await db.commit()
    return {"ok": True}


# --- Trade Journal ---

@router.get("/journal")
async def get_journal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает все сделки пользователя (новые первыми)."""
    result = await db.execute(
        select(TradeJournal)
        .where(TradeJournal.user_id == current_user.id)
        .order_by(TradeJournal.created_at.desc())
    )
    trades = result.scalars().all()
    return {
        "trades": [
            {"id": t.id, "data": json.loads(t.data_json), "created_at": t.created_at.isoformat()}
            for t in trades
        ]
    }


@router.post("/journal", status_code=201)
async def add_trade(
    body: TradeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Добавляет сделку в журнал."""
    trade = TradeJournal(
        user_id=current_user.id,
        data_json=json.dumps(body.data, ensure_ascii=False),
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return {"id": trade.id, "created_at": trade.created_at.isoformat()}


@router.delete("/journal/{trade_id}")
async def delete_trade(
    trade_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удаляет сделку (только свою)."""
    result = await db.execute(
        select(TradeJournal).where(
            TradeJournal.id == trade_id,
            TradeJournal.user_id == current_user.id,
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    await db.delete(trade)
    await db.commit()
    return {"ok": True}


# --- Аватар профиля ---

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Загружает фото профиля пользователя."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Только изображения")
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join("uploads", "avatars", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Файл не более 5 МБ")
    with open(path, "wb") as f:
        f.write(content)
    # Удаляем старый аватар
    if current_user.avatar_url:
        old_path = current_user.avatar_url.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)
    current_user.avatar_url = f"/uploads/avatars/{filename}"
    await db.commit()
    return {"avatar_url": current_user.avatar_url}


# --- Администрирование ---

@router.get("/admin/users")
async def admin_list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список всех пользователей (только для администраторов)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return {"users": [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удаляет пользователя и все его данные (только для администраторов, нельзя удалить себя)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить себя")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    await db.delete(user)
    await db.commit()
    return {"ok": True}
