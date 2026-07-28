"""
Модуль аутентификации — JWT-токены и зависимости FastAPI.
"""

import asyncio
import logging
import secrets
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_DAYS,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, FRONTEND_URL,
)
from database import User, get_db

logger = logging.getLogger(__name__)

# Контекст хеширования паролей (bcrypt, совместимость с bcrypt 4.x)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)

# Схема извлечения Bearer-токена из заголовка Authorization
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Хеширует пароль через bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет пароль против хеша."""
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    """Создаёт JWT с exp = сейчас + JWT_EXPIRE_DAYS дней."""
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Декодирует JWT. Возвращает None при ошибке."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Зависимость: обязательная авторизация. Кидает 401 если токен невалидный."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Токен не предоставлен")

    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалидный токен")

    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


def generate_reset_token() -> str:
    """Генерирует случайный токен сброса пароля."""
    return secrets.token_urlsafe(32)


def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


async def send_reset_email(to_email: str, token: str) -> None:
    """Отправляет письмо со ссылкой сброса пароля. Если SMTP не настроен — логирует ссылку в консоль."""
    link = f"{FRONTEND_URL}/?reset_token={token}"
    subject = "Force of Momentum — восстановление пароля"
    body = (
        f"Вы запросили восстановление пароля.\n\n"
        f"Перейдите по ссылке, чтобы задать новый пароль (действует 1 час):\n{link}\n\n"
        f"Если вы не запрашивали восстановление — просто игнорируйте это письмо."
    )
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP не настроен — ссылка сброса пароля для %s: %s", to_email, link)
        return
    try:
        await asyncio.to_thread(_send_email_sync, to_email, subject, body)
    except Exception:
        logger.exception("Не удалось отправить письмо сброса пароля на %s", to_email)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Зависимость: опциональная авторизация. Возвращает None если токена нет или он невалидный."""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    return result.scalar_one_or_none()
