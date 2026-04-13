"""
Модуль REST-маршрутов API.
Содержит все GET-эндпоинты: /health, /ohlcv, /alligator, /ao, /bwmfi.
Каждый эндпоинт поддерживает кеширование и rate-limiting.
"""

import asyncio
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pyrate_limiter import Duration, Rate, Limiter
from fastapi_limiter.depends import RateLimiter

from config import RATE_LIMIT_TIMES, RATE_LIMIT_SECONDS, EXCHANGE_ID
from cache import get_cache_key, get_cached_data, set_cached_data
from exchange import async_fetch_ohlcv_df, async_fetch_ticker, async_fetch_symbols, async_fetch_all_tickers
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences

# Маршрутизатор для REST API
router = APIRouter()

# Rate-limiter: RATE_LIMIT_TIMES запросов за RATE_LIMIT_SECONDS секунд
_limiter = Limiter(Rate(RATE_LIMIT_TIMES, Duration.SECOND * RATE_LIMIT_SECONDS))
rate_limit = Depends(RateLimiter(limiter=_limiter))


@router.get("/ticker")
async def get_ticker(symbol: str = "BTCUSDT"):
    """Текущая цена и 24ч статистика. Кеш 5 секунд."""
    key = get_cache_key(symbol, "", 0, "ticker")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        data = await async_fetch_ticker(symbol)
        await set_cached_data(key, data, ttl=5)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    """Проверка работоспособности API."""
    return {"status": "TradingView Clone API - Все индикаторы работают!"}


@router.get("/symbols")
async def get_symbols():
    """Список доступных USDT spot-пар с биржи."""
    key = get_cache_key("", "", 0, "symbols")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        symbols = await async_fetch_symbols()
        result = {"symbols": symbols, "count": len(symbols)}
        await set_cached_data(key, result, ttl=3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ohlcv", dependencies=[rate_limit])
async def get_ohlcv(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 100):
    """Получение OHLCV-данных (свечей) для указанного символа и таймфрейма."""
    key = get_cache_key(symbol, timeframe, limit, "ohlcv")
    cached = await get_cached_data(key)
    if cached:
        return {"cached": True, **cached}

    try:
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
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
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
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
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
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
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
        mfi, palette = calculate_bw_mfi(df, color_style)
        df_mfi = pd.DataFrame({
            'timestamp': df['timestamp'],
            'MFI': mfi.values,
            'color': palette
        })
        result = df_mfi.to_dict('records')
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
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
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
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)
        ao = calculate_ao(df)
        bearish, bullish = find_divergences(df, ao)
        response = {"symbol": symbol, "timeframe": timeframe, "bearish": bearish, "bullish": bullish}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Divergences: {str(e)}")


@router.get("/chart-data", dependencies=[rate_limit])
async def get_chart_data(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    """Комбинированный endpoint: OHLCV + все индикаторы за один запрос к бирже."""
    key = get_cache_key(symbol, timeframe, limit, "chart_data")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        # Один вызов к бирже
        df = await async_fetch_ohlcv_df(symbol, timeframe, limit)

        # OHLCV
        ohlcv = df.to_dict('records')

        # Alligator
        df_alligator = calculate_alligator(df)
        alligator = df_alligator.to_dict('records')

        # AO
        ao = calculate_ao(df)
        ao_data = [{"timestamp": t, "AO": v} for t, v in zip(df['timestamp'], ao.values)]

        # BW MFI
        mfi, palette = calculate_bw_mfi(df)
        bwmfi = [{"timestamp": t, "MFI": float(m), "color": c} for t, m, c in zip(df['timestamp'], mfi.values, palette)]

        # Fractals
        df_fractals = find_fractals(df)
        fractal_highs = df_fractals.dropna(subset=['Fractal_High'])[['timestamp', 'Fractal_High']].rename(columns={'Fractal_High': 'value'}).to_dict('records')
        fractal_lows = df_fractals.dropna(subset=['Fractal_Low'])[['timestamp', 'Fractal_Low']].rename(columns={'Fractal_Low': 'value'}).to_dict('records')

        # Divergences
        bearish, bullish = find_divergences(df, ao)

        response = {
            "symbol": symbol,
            "timeframe": timeframe,
            "data": ohlcv,
            "alligator": alligator,
            "ao": ao_data,
            "bwmfi": bwmfi,
            "fractal_highs": fractal_highs,
            "fractal_lows": fractal_lows,
            "bearish": bearish,
            "bullish": bullish,
        }
        await set_cached_data(key, response)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chart data: {str(e)}")


@router.get("/tickers")
async def get_tickers(symbols: str = ""):
    """Batch-запрос тикеров для нескольких символов за раз."""
    syms = [s.strip() for s in symbols.split(",") if s.strip()][:50]
    if not syms:
        return {"tickers": {}}

    async def fetch_one(sym):
        key = get_cache_key(sym, "", 0, "ticker")
        cached = await get_cached_data(key)
        if cached:
            return sym, cached
        try:
            data = await async_fetch_ticker(sym)
            await set_cached_data(key, data, ttl=5)
            return sym, data
        except Exception:
            return sym, None

    results = await asyncio.gather(*[fetch_one(s) for s in syms])
    return {"tickers": {sym: data for sym, data in results if data}}


@router.get("/tickers-all")
async def get_all_tickers():
    """Все USDT тикеры одним вызовом к бирже (кеш 5 сек)."""
    key = get_cache_key("", "", 0, "tickers_all")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        data = await async_fetch_all_tickers()
        result = {"tickers": data}
        await set_cached_data(key, result, ttl=5)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tickers: {str(e)}")
