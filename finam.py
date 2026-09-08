"""
Модуль для получения данных через Finam Trade API (только для админа).
Требует secret-токен из личного кабинета Финама (FINAM_SECRET_TOKEN в .env).
Документация: https://api.finam.ru/docs/rest/
"""

import httpx
import pandas as pd
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from config import FINAM_SECRET_TOKEN

FINAM_BASE_URL = "https://api.finam.ru"

# Таймфреймы: наш формат → формат Finam Trade API
FINAM_TIMEFRAMES = {
    '1m': 'TIME_FRAME_M1',
    '5m': 'TIME_FRAME_M5',
    '15m': 'TIME_FRAME_M15',
    '1h': 'TIME_FRAME_H1',
    '4h': 'TIME_FRAME_H4',
    '1d': 'TIME_FRAME_D',
    '1w': 'TIME_FRAME_W',
}

_INTERVAL_DELTA = {
    '1m': timedelta(minutes=1),
    '5m': timedelta(minutes=5),
    '15m': timedelta(minutes=15),
    '1h': timedelta(hours=1),
    '4h': timedelta(hours=4),
    '1d': timedelta(days=1),
    '1w': timedelta(weeks=1),
}

# JWT кешируется в памяти — живёт 15 минут на стороне Finam, обновляем с запасом
_jwt_cache: dict = {"token": None, "expires_at": None}

# Список инструментов меняется редко — кешируем на несколько часов
_assets_cache: dict = {"data": None, "expires_at": None}


def _require_token():
    if not FINAM_SECRET_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="Finam Trade API не настроен: отсутствует FINAM_SECRET_TOKEN на сервере",
        )


async def get_jwt_token() -> str:
    """
    Возвращает действующий JWT-токен, обновляя его при необходимости.
    Finam выдаёт JWT на 15 минут по secret-токену через POST /v1/sessions.
    """
    _require_token()

    now = datetime.now(timezone.utc)
    if _jwt_cache["token"] and _jwt_cache["expires_at"] and now < _jwt_cache["expires_at"]:
        return _jwt_cache["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{FINAM_BASE_URL}/v1/sessions",
                json={"secret": FINAM_SECRET_TOKEN},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Finam Trade API недоступен: {e}")

    if resp.status_code == 401 or resp.status_code == 403:
        raise HTTPException(
            status_code=502,
            detail="Finam Trade API отклонил secret-токен (401/403) — проверьте FINAM_SECRET_TOKEN",
        )
    resp.raise_for_status()

    data = resp.json()
    token = data.get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Finam Trade API не вернул JWT-токен")

    _jwt_cache["token"] = token
    # Запас в 1 минуту до истечения реального 15-минутного срока действия
    _jwt_cache["expires_at"] = now + timedelta(minutes=14)
    return token


async def _finam_get(path: str, params: dict | None = None) -> dict:
    token = await get_jwt_token()
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{FINAM_BASE_URL}{path}",
                params=params or {},
                headers={"Authorization": token},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Finam Trade API недоступен: {e}")

    if resp.status_code in (401, 403):
        # Токен мог протухнуть раньше срока — сбрасываем кеш на следующий запрос
        _jwt_cache["token"] = None
        raise HTTPException(status_code=502, detail="Finam Trade API отклонил запрос (401/403)")
    resp.raise_for_status()
    return resp.json()


async def fetch_ohlcv_finam(symbol: str, timeframe: str = '1d', limit: int = 100) -> pd.DataFrame:
    """
    Загружает OHLCV-свечи через Finam Trade API.
    symbol в формате TICKER@MIC, например SBER@MISX.
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume —
    тем же форматом, что и moex.fetch_ohlcv_moex(), чтобы indicators.py работал без изменений.
    """
    tf = FINAM_TIMEFRAMES.get(timeframe, 'TIME_FRAME_D')
    delta = _INTERVAL_DELTA.get(timeframe, timedelta(days=1))

    end_time = datetime.now(timezone.utc)
    start_time = end_time - delta * (limit + 5)

    data = await _finam_get(
        f"/v1/instruments/{symbol}/bars",
        params={
            "timeframe": tf,
            "interval.start_time": start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "interval.end_time": end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
    )

    bars = data.get("bars", [])
    if not bars:
        raise ValueError(f"Finam Trade API: нет данных для {symbol} ({timeframe})")

    def _num(field):
        """Finam оборачивает числа в {"value": "123.45"} (protobuf Decimal)."""
        if isinstance(field, dict):
            return float(field.get('value', 0) or 0)
        return float(field or 0)

    result = pd.DataFrame({
        'timestamp': [pd.to_datetime(b['timestamp']).strftime('%Y-%m-%d %H:%M:%S') for b in bars],
        'Open': [_num(b['open']) for b in bars],
        'High': [_num(b['high']) for b in bars],
        'Low': [_num(b['low']) for b in bars],
        'Close': [_num(b['close']) for b in bars],
        'Volume': [_num(b.get('volume', 0)) for b in bars],
    })

    return result.tail(limit).reset_index(drop=True)


async def fetch_finam_assets() -> list:
    """
    Возвращает список доступных инструментов Finam Trade API (тикер, биржа, название).
    Кешируется в памяти на несколько часов.
    """
    now = datetime.now(timezone.utc)
    if _assets_cache["data"] is not None and _assets_cache["expires_at"] and now < _assets_cache["expires_at"]:
        return _assets_cache["data"]

    data = await _finam_get("/v1/assets")
    assets = data.get("assets", [])

    _assets_cache["data"] = assets
    _assets_cache["expires_at"] = now + timedelta(hours=6)
    return assets


async def fetch_finam_quote(symbol: str) -> dict:
    """Возвращает последнюю котировку по инструменту (TICKER@MIC)."""
    data = await _finam_get(f"/v1/instruments/{symbol}/quotes/latest")
    return data.get("quote", {})
