"""
Роутер /support — чат 1-на-1 между пользователем и администратором.
Заменяет старую модель "жалоба -> один ответ админа кнопкой «обработано»"
на обычную переписку: обращение пользователя открывает тред, админ отвечает
в нём как в чате. "Обработано" относится только к самому первому обращению
(см. SupportThread.acknowledged) — к остальным сообщениям статус не применяется.

Доставка в реальном времени и уведомление администратора (сайдбар мигает +
звук) идут через WS /ws/support, REST — для отправки (нужна загрузка файла)
и истории.
"""

import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, decode_token
from database import get_db, SupportThread, SupportMessage, User, async_session

router = APIRouter(prefix="/support", tags=["support"])
# Отдельный роутер без префикса — иначе /support/ws/support вместо /ws/support
# (тот же приём, что у /ws/chat в chat.py: регистрировать ДО ws_router в main.py).
ws_router = APIRouter(tags=["support"])

UPLOAD_DIR = Path("uploads/feedback")  # тот же каталог, что и у старых жалоб
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# ── WebSocket: уведомления в реальном времени ──────────────────────

class _SupportConnectionManager:
    def __init__(self):
        # {websocket: {"user_id": int, "is_admin": bool}}
        self.active: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, user_id: int, is_admin: bool):
        await ws.accept()
        self.active[ws] = {"user_id": user_id, "is_admin": is_admin}

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws, None)

    async def _send(self, ws: WebSocket, payload: dict):
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def notify_admins(self, payload: dict):
        for ws, info in list(self.active.items()):
            if info["is_admin"]:
                await self._send(ws, payload)

    async def notify_user(self, user_id: int, payload: dict):
        for ws, info in list(self.active.items()):
            if not info["is_admin"] and info["user_id"] == user_id:
                await self._send(ws, payload)


manager = _SupportConnectionManager()


@ws_router.websocket("/ws/support")
async def support_ws(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """?token=<jwt>. Только уведомления (новое сообщение пришло) — сам текст
    отправляется через REST POST /support/message, чтобы заодно поддержать
    загрузку скриншота (WS для файлов неудобен)."""
    await ws.accept()
    if not token:
        await ws.close(code=4001)
        return
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        await ws.close(code=4001)
        return

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == int(payload["sub"])))
        user = result.scalar_one_or_none()
        if not user:
            await ws.close(code=4001)
            return

        manager.active[ws] = {"user_id": user.id, "is_admin": user.is_admin}
        try:
            while True:
                await ws.receive_text()  # клиент ничего не шлёт, но держим соединение живым
        except WebSocketDisconnect:
            manager.disconnect(ws)


# ── REST ────────────────────────────────────────────────────────────

async def _get_or_create_thread(db: AsyncSession, user: User) -> SupportThread:
    result = await db.execute(select(SupportThread).where(SupportThread.user_id == user.id))
    thread = result.scalar_one_or_none()
    if not thread:
        thread = SupportThread(user_id=user.id, username=user.username)
        db.add(thread)
        await db.flush()
    return thread


@router.post("/message")
async def send_message(
    message: str = Form(...),
    user_id: Optional[int] = Form(default=None),  # только для админа: кому отвечает
    screenshot: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    if current_user.is_admin:
        if not user_id:
            raise HTTPException(status_code=400, detail="Не указан получатель")
        result = await db.execute(select(SupportThread).where(SupportThread.user_id == user_id))
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Тред не найден")
    else:
        thread = await _get_or_create_thread(db, current_user)
        user_id = current_user.id

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

    msg = SupportMessage(
        user_id=user_id,
        sender_is_admin=current_user.is_admin,
        sender_username=current_user.username,
        message=message,
        screenshot_path=screenshot_path,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    thread.last_message_at = msg.created_at
    await db.commit()

    payload = {
        "type": "new_message",
        "id": msg.id,
        "user_id": user_id,
        "username": thread.username,
        "sender_username": msg.sender_username,
        "is_admin": msg.sender_is_admin,
        "text": msg.message,
        "screenshot_url": f"/uploads/feedback/{msg.screenshot_path}" if msg.screenshot_path else None,
        "created_at": msg.created_at.isoformat(),
    }
    if current_user.is_admin:
        await manager.notify_user(user_id, payload)
    else:
        await manager.notify_admins(payload)

    return {
        "id": msg.id,
        "is_admin": msg.sender_is_admin,
        "sender_username": msg.sender_username,
        "text": msg.message,
        "screenshot_url": payload["screenshot_url"],
        "created_at": msg.created_at.isoformat(),
    }


@router.get("/messages")
async def get_messages(
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обычный пользователь — всегда свой тред. Админ — обязателен user_id."""
    if current_user.is_admin:
        if not user_id:
            raise HTTPException(status_code=400, detail="Не указан user_id")
        target_id = user_id
    else:
        target_id = current_user.id

    result = await db.execute(select(SupportThread).where(SupportThread.user_id == target_id))
    thread = result.scalar_one_or_none()
    if not thread:
        return {"messages": [], "acknowledged": False}

    result = await db.execute(
        select(SupportMessage).where(SupportMessage.user_id == target_id).order_by(SupportMessage.created_at)
    )
    messages = result.scalars().all()

    # Просмотр треда прочитывает сообщения ОТ ДРУГОЙ стороны
    unread_from_other = [
        m for m in messages if m.sender_is_admin != current_user.is_admin and not m.read
    ]
    for m in unread_from_other:
        m.read = True
    if unread_from_other:
        await db.commit()

    return {
        "acknowledged": thread.acknowledged,
        "messages": [
            {
                "id": m.id,
                "is_admin": m.sender_is_admin,
                "sender_username": m.sender_username,
                "text": m.message,
                "screenshot_url": f"/uploads/feedback/{m.screenshot_path}" if m.screenshot_path else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.get("/threads")
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список тредов — только admin. Сортировка по последнему сообщению."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(select(SupportThread).order_by(SupportThread.last_message_at.desc()))
    threads = result.scalars().all()

    items = []
    for t in threads:
        last_result = await db.execute(
            select(SupportMessage)
            .where(SupportMessage.user_id == t.user_id)
            .order_by(SupportMessage.created_at.desc())
            .limit(1)
        )
        last = last_result.scalar_one_or_none()
        unread_result = await db.execute(
            select(func.count()).select_from(SupportMessage).where(
                and_(
                    SupportMessage.user_id == t.user_id,
                    SupportMessage.sender_is_admin.is_(False),
                    SupportMessage.read.is_(False),
                )
            )
        )
        unread = unread_result.scalar() or 0
        items.append({
            "user_id": t.user_id,
            "username": t.username,
            "acknowledged": t.acknowledged,
            "unread_count": unread,
            "last_message": last.message if last else "",
            "last_message_at": t.last_message_at.isoformat(),
        })

    return {"threads": items}


@router.post("/{user_id}/acknowledge")
async def acknowledge_thread(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отметить ПЕРВОЕ обращение обработанным — только admin. Пользователь
    увидит подтверждение только после этого, не раньше (в отличие от старой
    логики, где статус был виден сразу)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")

    result = await db.execute(select(SupportThread).where(SupportThread.user_id == user_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Тред не найден")

    thread.acknowledged = True
    await db.commit()

    await manager.notify_user(user_id, {"type": "acknowledged", "user_id": user_id})
    return {"ok": True}


@router.get("/unread_count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Для бейджа на иконке без открытия панели."""
    if current_user.is_admin:
        result = await db.execute(
            select(func.count()).select_from(SupportMessage).where(
                and_(SupportMessage.sender_is_admin.is_(False), SupportMessage.read.is_(False))
            )
        )
    else:
        result = await db.execute(
            select(func.count()).select_from(SupportMessage).where(
                and_(
                    SupportMessage.user_id == current_user.id,
                    SupportMessage.sender_is_admin.is_(True),
                    SupportMessage.read.is_(False),
                )
            )
        )
    return {"count": result.scalar() or 0}
