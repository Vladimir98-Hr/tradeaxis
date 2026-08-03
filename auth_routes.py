"""
Роутер аутентификации: регистрация, вход, текущий пользователь, сброс пароля.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import RESET_TOKEN_EXPIRE_MINUTES
from database import User, get_db
from auth import (
    hash_password, verify_password, create_access_token, get_current_user,
    generate_reset_token, send_reset_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Схемы запросов/ответов ---

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Имя пользователя минимум 3 символа")
        if len(v) > 50:
            raise ValueError("Имя пользователя максимум 50 символов")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Только буквы, цифры, _ и -")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль минимум 6 символов")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool = False
    avatar_url: str | None = None

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# --- Endpoints ---

@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(times=5, seconds=300))],
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Регистрация нового пользователя."""
    # Проверка уникальности username
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")

    # Проверка уникальности email
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    # Первый зарегистрированный пользователь — администратор
    count_result = await db.execute(select(func.count()).select_from(User))
    is_first_user = (count_result.scalar() == 0)

    user = User(
        username=body.username,
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
        is_admin=is_first_user,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post(
    "/login", response_model=AuthResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=300))],
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Вход по username + password."""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    token = create_access_token({"sub": str(user.id)})
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Возвращает данные текущего авторизованного пользователя."""
    return current_user


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль минимум 6 символов")
        return v


@router.post(
    "/forgot-password",
    dependencies=[Depends(RateLimiter(times=5, seconds=300))],
)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Запрос на восстановление пароля. Всегда возвращает один и тот же ответ,
    чтобы не раскрывать, зарегистрирован ли такой email."""
    result = await db.execute(select(User).where(User.email == body.email.strip().lower()))
    user = result.scalar_one_or_none()
    if user:
        user.reset_token = generate_reset_token()
        user.reset_token_expires = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
        await db.commit()
        await send_reset_email(user.email, user.reset_token)
    return {"message": "Если такой email зарегистрирован, на него отправлено письмо со ссылкой для сброса пароля"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Устанавливает новый пароль по токену из письма."""
    result = await db.execute(select(User).where(User.reset_token == body.token))
    user = result.scalar_one_or_none()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Ссылка недействительна или устарела")

    user.hashed_password = hash_password(body.password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    return {"message": "Пароль успешно изменён"}
