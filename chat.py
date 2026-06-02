"""
WebSocket-чат сообщества.
Только для зарегистрированных пользователей (токен в query-параметре).
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import ChatMessage, async_session
from auth import decode_token
from database import User

router = APIRouter(tags=["chat"])


class ConnectionManager:
    """Менеджер активных WebSocket-соединений."""

    def __init__(self):
        # {websocket: {"user_id": int, "username": str}}
        self.active: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, user_id: int, username: str):
        await ws.accept()
        self.active[ws] = {"user_id": user_id, "username": username}

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws, None)

    async def broadcast(self, message: dict):
        """Отправляет сообщение всем подключённым клиентам."""
        data = json.dumps(message, ensure_ascii=False)
        disconnected = []
        for ws in list(self.active.keys()):
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    def online_count(self) -> int:
        return len(self.active)


manager = ConnectionManager()


async def _get_history(db: AsyncSession, limit: int = 50) -> list[dict]:
    """Загружает последние N сообщений из БД (в хронологическом порядке)."""
    result = await db.execute(
        select(ChatMessage, User.is_admin)
        .join(User, ChatMessage.user_id == User.id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    rows = list(reversed(result.all()))
    return [
        {
            "type": "message",
            "id": m.id,
            "user_id": m.user_id,
            "username": m.username,
            "text": m.message,
            "timestamp": m.created_at.isoformat(),
            "is_admin": is_admin,
        }
        for m, is_admin in rows
    ]


async def _save_message(db: AsyncSession, user_id: int, username: str, text: str) -> ChatMessage:
    """Сохраняет сообщение в БД и обрезает историю до 500 записей."""
    msg = ChatMessage(user_id=user_id, username=username, message=text)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # Удаляем старые сообщения, если больше 500
    result = await db.execute(select(ChatMessage).order_by(desc(ChatMessage.created_at)).offset(500))
    old = result.scalars().all()
    for old_msg in old:
        await db.delete(old_msg)
    if old:
        await db.commit()

    return msg


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """
    WebSocket-чат сообщества.
    Параметр: ?token=<jwt>
    Если токен невалидный — соединение отклоняется.
    """
    # Сначала принимаем соединение, потом валидируем токен
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

        # Регистрируем соединение
        manager.active[ws] = {"user_id": user.id, "username": user.username}

        # Отправляем историю
        history = await _get_history(db)
        await ws.send_text(json.dumps({"type": "history", "messages": history}, ensure_ascii=False))

        # Отправляем статус онлайн
        await manager.broadcast({"type": "online", "count": manager.online_count()})

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if data.get("type") != "message":
                    continue

                text = str(data.get("text", "")).strip()
                if not text or len(text) > 1000:
                    continue

                # Сохраняем в БД
                msg = await _save_message(db, user.id, user.username, text)

                # Рассылаем всем
                await manager.broadcast({
                    "type": "message",
                    "id": msg.id,
                    "user_id": user.id,
                    "username": user.username,
                    "text": text,
                    "timestamp": msg.created_at.isoformat(),
                    "is_admin": user.is_admin,
                })

        except WebSocketDisconnect:
            manager.disconnect(ws)
            await manager.broadcast({"type": "online", "count": manager.online_count()})


@router.delete("/chat/message/{message_id}")
async def delete_chat_message(
    message_id: int,
    token: Optional[str] = Query(default=None),
):
    """Удаление сообщения из чата (только для администратора)."""
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Невалидный токен")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == int(payload["sub"])))
        user = result.scalar_one_or_none()
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="Требуются права администратора")

        result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
        msg = result.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")

        await db.delete(msg)
        await db.commit()

    await manager.broadcast({"type": "delete_message", "id": message_id})
    return {"ok": True}
