"""
Роутер сверки результата дня: хранение read-only биржевых API-ключей
пользователя и подсчёт дневного P&L (сделки/комиссии/funding/переводы).
См. exchange_private.py (приватные вызовы к бирже) и crypto_utils.py (шифрование).
"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import User, ExchangeCredential, get_db
from auth import get_current_user
from cache import get_cache_key, get_or_compute
from crypto_utils import encrypt, decrypt
from exchange_private import SUPPORTED_EXCHANGES, verify_credentials, fetch_daily_summary

router = APIRouter(prefix="/user/exchange-credentials", tags=["exchange-credentials"])
pnl_router = APIRouter(prefix="/user/pnl", tags=["exchange-credentials"])


class CredentialBody(BaseModel):
    exchange_id: str
    label: str
    api_key: str
    api_secret: str
    api_passphrase: str | None = None


def _mask(key: str) -> str:
    if len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


def _to_public(cred: ExchangeCredential) -> dict:
    return {
        "id": cred.id,
        "exchange_id": cred.exchange_id,
        "label": cred.label,
        "api_key_masked": _mask(decrypt(cred.api_key_enc)),
        "created_at": cred.created_at.isoformat(),
        "last_synced_at": cred.last_synced_at.isoformat() if cred.last_synced_at else None,
        "last_sync_status": cred.last_sync_status,
        "last_sync_error": cred.last_sync_error,
    }


@router.get("")
async def list_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeCredential).where(ExchangeCredential.user_id == current_user.id)
    )
    return {"credentials": [_to_public(c) for c in result.scalars().all()]}


@router.post("")
async def add_credential(
    body: CredentialBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exchange_id = body.exchange_id.strip().lower()
    if exchange_id not in SUPPORTED_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Биржа '{exchange_id}' пока не поддерживается")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{8,200}", body.api_key.strip()):
        raise HTTPException(status_code=400, detail="Похоже на невалидный формат API-ключа")

    # Тестовый read-only вызов ДО сохранения — невалидный/недостаточно прав ключ не сохраняем.
    try:
        await verify_credentials(exchange_id, body.api_key.strip(), body.api_secret.strip(), body.api_passphrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cred = ExchangeCredential(
        user_id=current_user.id,
        exchange_id=exchange_id,
        label=body.label.strip() or exchange_id,
        api_key_enc=encrypt(body.api_key.strip()),
        api_secret_enc=encrypt(body.api_secret.strip()),
        api_passphrase_enc=encrypt(body.api_passphrase.strip()) if body.api_passphrase else None,
        last_synced_at=datetime.now(timezone.utc),
        last_sync_status="ok",
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return _to_public(cred)


@router.delete("/{credential_id}")
async def delete_credential(
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeCredential).where(
            ExchangeCredential.id == credential_id,
            ExchangeCredential.user_id == current_user.id,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Ключ не найден")
    await db.execute(delete(ExchangeCredential).where(ExchangeCredential.id == credential_id))
    await db.commit()
    return {"ok": True}


@pnl_router.get("/daily")
async def get_daily_pnl(
    date: str,
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Сводка P&L за день по одному подключённому ключу. Кешируется в Redis на
    несколько минут — ключ кеша обязательно включает user_id, чтобы ни при
    каких условиях не отдать данные не тому пользователю (см. cache.py).
    По запросу (при открытии панели), без фоновых воркеров — см. урок с Finam
    в plan-файле: не плодить постоянные циклы на пользователя.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="date должен быть в формате YYYY-MM-DD")

    result = await db.execute(
        select(ExchangeCredential).where(
            ExchangeCredential.id == credential_id,
            ExchangeCredential.user_id == current_user.id,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Ключ не найден")

    cache_key = get_cache_key(f"user{current_user.id}", f"cred{credential_id}", 0, f"pnl_daily_{date}")

    async def compute():
        api_key = decrypt(cred.api_key_enc)
        api_secret = decrypt(cred.api_secret_enc)
        api_passphrase = decrypt(cred.api_passphrase_enc) if cred.api_passphrase_enc else None
        try:
            summary = await fetch_daily_summary(cred.exchange_id, api_key, api_secret, api_passphrase, date)
            cred.last_synced_at = datetime.now(timezone.utc)
            cred.last_sync_status = "ok" if not summary["partial"] else "partial"
            cred.last_sync_error = "; ".join(summary["errors"]) if summary["errors"] else None
        except Exception as e:
            cred.last_sync_status = "error"
            cred.last_sync_error = str(e)
            await db.commit()
            raise HTTPException(status_code=502, detail=f"Не удалось получить данные с биржи: {e}")
        await db.commit()
        return summary

    return await get_or_compute(cache_key, compute, ttl=180)
