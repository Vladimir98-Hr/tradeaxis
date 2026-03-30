"""
Модуль REST-маршрутов API.
Содержит все GET-эндпоинты: /health, /ohlcv, /alligator, /ao, /bwmfi.
Каждый эндпоинт поддерживает кеширование и rate-limiting.
"""

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Limiter, Rate, Duration

from config import RATE_LIMIT_TIMES, RATE_LIMIT_SECONDS, EXCHANGE_ID
from cache import get_cache_key, get_cached_data, set_cached_data
from exchange import fetch_ohlcv_df, fetch_ticker
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences

# Маршрутизатор для REST API
router = APIRouter()

# Rate-limiter: RATE_LIMIT_TIMES запросов за RATE_LIMIT_SECONDS секунд
_rate = Rate(RATE_LIMIT_TIMES, RATE_LIMIT_SECONDS * Duration.SECOND)
_limiter = Limiter(_rate)
rate_limit = Depends(RateLimiter(_limiter))


@router.get("/ticker")
async def get_ticker(symbol: str = "BTCUSDT"):
    """Текущая цена и 24ч статистика. Кеш 5 секунд."""
    key = get_cache_key(symbol, "", 0, "ticker")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        data = fetch_ticker(symbol)
        await set_cached_data(key, data, ttl=5)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    """Проверка работоспособности API."""
    return {"status": "TradingView Clone API - Все индикаторы работают!"}


@router.get("/ohlcv", dependencies=[rate_limit])
async def get_ohlcv(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 100):
    """Получение OHLCV-данных (свечей) для указанного символа и таймфрейма."""
    key = get_cache_key(symbol, timeframe, limit, "ohlcv")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        result = df.to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "data": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{EXCHANGE_ID}: {str(e)}")


@router.get("/alligator", dependencies=[rate_limit])
async def get_alligator(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    """Получение данных индикатора Alligator."""
    key = get_cache_key(symbol, timeframe, limit, "alligator")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        df_alligator = calculate_alligator(df)
        result = df_alligator.tail(100).to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "alligator": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alligator: {str(e)}")


@router.get("/ao", dependencies=[rate_limit])
async def get_ao(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    """Получение данных Awesome Oscillator (AO)."""
    key = get_cache_key(symbol, timeframe, limit, "ao")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        ao = calculate_ao(df)
        df_ao = pd.DataFrame({'timestamp': df['timestamp'], 'AO': ao.values})
        result = df_ao.to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "ao": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AO: {str(e)}")


@router.get("/bwmfi", dependencies=[rate_limit])
async def get_bwmfi(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200, color_style: bool = False):
    """Получение данных Bill Williams Market Facilitation Index."""
    key = get_cache_key(symbol, timeframe, limit, f"bwmfi_{color_style}")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        mfi, palette = calculate_bw_mfi(df, color_style)
        df_mfi = pd.DataFrame({
            'timestamp': df['timestamp'],
            'MFI': mfi.values,
            'color': palette
        })
        result = df_mfi.tail(100).to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "bwmfi": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BW MFI: {str(e)}")


@router.get("/fractals", dependencies=[rate_limit])
async def get_fractals(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    """Определение фракталов (локальных максимумов и минимумов)."""
    key = get_cache_key(symbol, timeframe, limit, "fractals")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        df_fractals = find_fractals(df)
        highs = df_fractals.dropna(subset=['Fractal_High'])[['timestamp', 'Fractal_High']].rename(columns={'Fractal_High': 'value'}).to_dict('records')
        lows = df_fractals.dropna(subset=['Fractal_Low'])[['timestamp', 'Fractal_Low']].rename(columns={'Fractal_Low': 'value'}).to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "fractal_highs": highs, "fractal_lows": lows}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fractals: {str(e)}")


@router.get("/divergences", dependencies=[rate_limit])
async def get_divergences(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    """Поиск бычьих и медвежьих дивергенций по AO."""
    key = get_cache_key(symbol, timeframe, limit, "divergences")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        ao = calculate_ao(df)
        bearish, bullish = find_divergences(df, ao)
        response = {"symbol": symbol, "timeframe": timeframe, "bearish": bearish, "bullish": bullish}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Divergences: {str(e)}")
