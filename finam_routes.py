"""
Роутер для Finam Trade API — доступен всем зарегистрированным пользователям
(токен привязан к брокерскому счёту сервиса, но используется только для чтения
публичных рыночных данных Мосбиржи — котировки и свечи, без операций со счётом).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import User
from config import FINAM_SYMBOLS, FINAM_INSTRUMENTS
from cache import get_cache_key, get_cached_data, set_cached_data
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands
from finam import fetch_ohlcv_finam, fetch_finam_assets
from routes import _check_last_bar_divergence

router = APIRouter(prefix="/finam", tags=["finam"])


def _curated_instruments(category: str) -> list:
    """Curated-список инструментов Finam из config.py по категории."""
    if category == "stocks":
        return [
            {"symbol": f"{k}@MISX", "name": v["name"], "base": v["base"], "cat": "stocks"}
            for k, v in FINAM_SYMBOLS.items()
        ]
    return [
        {"symbol": k, "name": v["name"], "base": k.split("@")[0], "cat": v["cat"]}
        for k, v in FINAM_INSTRUMENTS.items()
        if v["cat"] == category
    ]


@router.get("/symbols")
async def get_finam_symbols(category: str = "stocks", current_user: User = Depends(get_current_user)):
    """
    Список инструментов Finam по категории: stocks | futures | currencies | commodities.
    Сначала отдаём проверенный curated-список из config.py (гарантированно рабочий),
    затем пытаемся расширить его живыми данными /v1/assets/all — если Finam недоступен
    или список категории не поддерживается, тихо остаёмся на curated-only.
    """
    curated = _curated_instruments(category)
    curated_symbols = {c["symbol"] for c in curated}

    extra = []
    try:
        # Живое расширение поверх curated-списка включаем только там, где категория
        # однозначно определяется одной биржей Finam (mic), иначе типы пересекаются:
        # - currencies/commodities у Finam оба размечены типом CURRENCIES;
        # - товарные/индексные/облигационные мировые фьючерсы делят одни и те же биржи
        #   (например XCBT — и пшеница, и облигации США), их разделяет только curated-список.
        # stocks (акции Мосбиржи, MISX) и futures (фьючерсы Мосбиржи, RTSX) — безопасны.
        type_mic_map = {"stocks": ("EQUITIES", "MISX"), "futures": ("FUTURES", "RTSX")}
        wanted = type_mic_map.get(category)
        if wanted:
            wanted_type, wanted_mic = wanted
            assets = await fetch_finam_assets()
            for a in assets:
                sym = a.get("symbol")
                if not sym or sym in curated_symbols:
                    continue
                if a.get("type") != wanted_type or a.get("mic") != wanted_mic:
                    continue
                extra.append({"symbol": sym, "name": a.get("name") or sym, "base": a.get("ticker", sym), "cat": category})
    except HTTPException:
        pass

    return {"category": category, "symbols": curated + extra}


@router.get("/chart-data")
async def get_finam_chart_data(
    symbol: str = "SBER@MISX",
    timeframe: str = "1d",
    limit: int = 200,
    current_user: User = Depends(get_current_user),
):
    """Комбинированный Finam endpoint: OHLCV + все индикаторы."""
    key = get_cache_key(symbol, timeframe, limit, "finam_chart")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        df = await fetch_ohlcv_finam(symbol, timeframe, limit)

        ohlcv = df.to_dict("records")
        df_alligator = calculate_alligator(df)
        alligator = df_alligator.to_dict("records")
        ao = calculate_ao(df)
        ao_data = [{"timestamp": t, "AO": v} for t, v in zip(df["timestamp"], ao.values)]
        mfi, palette = calculate_bw_mfi(df)
        bwmfi = [{"timestamp": t, "MFI": float(m), "color": c}
                 for t, m, c in zip(df["timestamp"], mfi.values, palette)]
        df_fractals = find_fractals(df)
        fractal_highs = (df_fractals.dropna(subset=["Fractal_High"])
                         [["timestamp", "Fractal_High"]]
                         .rename(columns={"Fractal_High": "value"})
                         .to_dict("records"))
        fractal_lows = (df_fractals.dropna(subset=["Fractal_Low"])
                        [["timestamp", "Fractal_Low"]]
                        .rename(columns={"Fractal_Low": "value"})
                        .to_dict("records"))
        bearish, bullish = find_divergences(df, ao)
        df_bb = calculate_bollinger_bands(df)
        bollinger = df_bb.to_dict("records")

        response = {
            "symbol": symbol, "timeframe": timeframe,
            "data": ohlcv, "alligator": alligator, "ao": ao_data,
            "bwmfi": bwmfi, "fractal_highs": fractal_highs, "fractal_lows": fractal_lows,
            "bearish": bearish, "bullish": bullish, "bollinger": bollinger,
        }
        await set_cached_data(key, response, ttl=300)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finam chart: {str(e)}")


def _all_instruments() -> list:
    """Все curated-инструменты Finam (акции + фьючерсы + валюты + сырьё) для сканеров."""
    instruments = [
        {"symbol": f"{k}@MISX", "name": v["name"], "base": v["base"], "cat": "stocks"}
        for k, v in FINAM_SYMBOLS.items()
    ]
    instruments += [
        {"symbol": k, "name": v["name"], "base": k.split("@")[0], "cat": v["cat"]}
        for k, v in FINAM_INSTRUMENTS.items()
    ]
    return instruments


@router.get("/scan/volatile")
async def finam_scan_volatile(threshold: float = 1.0, top: int = 20, current_user: User = Depends(get_current_user)):
    """Инструменты Finam с высокой волатильностью за последние ~30 минут (5m свечи)."""
    key = get_cache_key("finam_vol", "5m", top, f"finam_volatile_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    sem = asyncio.Semaphore(6)

    async def scan_one(inst):
        async with sem:
            try:
                df = await fetch_ohlcv_finam(inst["symbol"], "5m", 14)
                if len(df) < 8:
                    return None
                closes = df["Close"].values
                change_30m = (closes[-1] - closes[-7]) / closes[-7] * 100
                bar_changes = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(1, len(closes))]
                oscillation = sum(abs(c) for c in bar_changes) / len(bar_changes)
                score = abs(change_30m) + oscillation * 3
                if abs(change_30m) < threshold:
                    return None
                return {
                    "symbol": inst["symbol"], "name": inst["name"], "base": inst["base"],
                    "price": float(closes[-1]),
                    "change_30m": round(change_30m, 2),
                    "oscillation": round(oscillation, 3),
                    "score": round(score, 2),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(inst) for inst in _all_instruments()])
    pairs = [r for r in results if r]
    pairs.sort(key=lambda x: x["score"], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=300)
    return response


@router.get("/scan/spread")
async def finam_scan_spread(threshold: float = 1.0, top: int = 20, current_user: User = Depends(get_current_user)):
    """Инструменты Finam с широким спредом свечи за 15 минут (High-Low)/Low >= threshold%."""
    key = get_cache_key("finam_spread", "15m", top, f"finam_spread15_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    sem = asyncio.Semaphore(6)

    async def scan_one(inst):
        async with sem:
            try:
                df = await fetch_ohlcv_finam(inst["symbol"], "15m", 3)
                if len(df) < 1:
                    return None
                high = float(df["High"].iloc[-1])
                low = float(df["Low"].iloc[-1])
                close = float(df["Close"].iloc[-1])
                if low <= 0:
                    return None
                spread = (high - low) / low * 100
                if spread < threshold:
                    return None
                return {
                    "symbol": inst["symbol"], "name": inst["name"], "base": inst["base"],
                    "price": round(close, 4),
                    "spread": round(spread, 2),
                    "high": round(high, 4),
                    "low": round(low, 4),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(inst) for inst in _all_instruments()])
    pairs = [r for r in results if r]
    pairs.sort(key=lambda x: x["spread"], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=300)
    return response


@router.get("/scan/divergences")
async def finam_scan_divergences(timeframe: str = "1d", limit: int = 50, current_user: User = Depends(get_current_user)):
    """Сканирует все инструменты Finam на дивергентный бар последнего закрытого бара."""
    cache_ttl = 3600 if timeframe in ("1d", "1w") else 900
    key = get_cache_key("finam_scan", timeframe, limit, "finam_scan_div")
    cached = await get_cached_data(key)
    if cached:
        return cached

    instruments = _all_instruments()
    sem = asyncio.Semaphore(6)

    async def scan_one(inst):
        async with sem:
            try:
                df = await fetch_ohlcv_finam(inst["symbol"], timeframe, limit)
                if len(df) < 10:
                    return None
                ao = calculate_ao(df)
                is_bull, is_bear = _check_last_bar_divergence(df, ao)
                if not is_bull and not is_bear:
                    return None
                return {
                    "symbol": inst["symbol"], "name": inst["name"], "cat": inst["cat"],
                    "type": "bull" if is_bull else "bear",
                    "close": float(df["Close"].iloc[-1]),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(inst) for inst in instruments])
    divergences = [r for r in results if r]
    response = {
        "timeframe": timeframe,
        "count": len(divergences),
        "scanned": len(instruments),
        "divergences": divergences,
    }
    await set_cached_data(key, response, ttl=cache_ttl)
    return response
