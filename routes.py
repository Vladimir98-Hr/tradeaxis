"""
Модуль REST-маршрутов API.
Содержит все GET-эндпоинты: /health, /ohlcv, /alligator, /ao, /bwmfi.
Каждый эндпоинт поддерживает кеширование и rate-limiting.
"""

import asyncio
import pandas as pd
from fastapi import APIRouter, HTTPException

from config import EXCHANGE_ID, MOEX_SYMBOLS, MOEX_FUTURES
from cache import get_cache_key, get_cached_data, set_cached_data
from exchange import async_fetch_ohlcv_df, async_fetch_ticker, async_fetch_symbols, async_fetch_all_tickers
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands
from moex import fetch_ohlcv_moex, fetch_ohlcv_moex_futures, fetch_moex_tickers

# Маршрутизатор для REST API
router = APIRouter()


def _check_last_bar_divergence(df, ao):
    """Проверяет есть ли дивергентный бар на последнем баре (логика из Pine Script / ccxt-сканера)."""
    i = len(df) - 1
    if i < 4:
        return False, False
    low_window = df['Low'].iloc[i - 4:i + 1].values
    is_bull = (
        bool(df['Low'].iloc[i] <= low_window.min()) and
        bool(ao.iloc[i] > ao.iloc[i - 1]) and
        bool(df['Low'].iloc[i] < df['Low'].iloc[i - 1])
    )
    high_window = df['High'].iloc[i - 4:i + 1].values
    is_bear = (
        bool(df['High'].iloc[i] >= high_window.max()) and
        bool(ao.iloc[i] < ao.iloc[i - 1]) and
        bool(df['High'].iloc[i] > df['High'].iloc[i - 1])
    )
    return is_bull, is_bear

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
    return {"status": "Force of Momentum API - Все индикаторы работают!"}


@router.get("/symbols")
async def get_symbols():
    """Список доступных USDT spot-пар с биржи + тикеры MOEX."""
    key = get_cache_key("", "", 0, "symbols_v2")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        crypto = await async_fetch_symbols()
        result = {
            "symbols": crypto,
            "count": len(crypto),
            "moex": list(MOEX_SYMBOLS.keys()),
        }
        await set_cached_data(key, result, ttl=3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/moex/ohlcv")
async def get_moex_ohlcv(symbol: str = "SBER", timeframe: str = "1d", limit: int = 100):
    """OHLCV-данные с Московской биржи через MOEX ISS (без токена)."""
    sym = symbol.upper()
    key = get_cache_key(sym, timeframe, limit, "moex_ohlcv")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        df = await fetch_ohlcv_moex(sym, timeframe, limit)
        data = df.to_dict("records")
        result = {"symbol": sym, "timeframe": timeframe, "count": len(data), "data": data}
        await set_cached_data(key, result, ttl=300)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MOEX: {str(e)}")


@router.get("/moex/symbols")
async def get_moex_symbols(category: str = "stocks"):
    """Список инструментов MOEX по категории: stocks | futures | commodities."""
    key = get_cache_key("", "", 0, f"moex_symbols_{category}")
    cached = await get_cached_data(key)
    if cached:
        return cached
    if category == "stocks":
        symbols = [
            {"symbol": k, "name": v["name"], "base": v["base"]}
            for k, v in MOEX_SYMBOLS.items()
        ]
    else:
        symbols = [
            {"symbol": k, "name": v["name"], "base": k}
            for k, v in MOEX_FUTURES.items()
            if v["cat"] == category
        ]
    result = {"category": category, "symbols": symbols}
    await set_cached_data(key, result, ttl=3600)
    return result


@router.get("/moex/tickers")
async def get_moex_tickers(category: str = "stocks"):
    """Текущие цены и изменение для инструментов MOEX по категории."""
    key = get_cache_key("", "", 0, f"moex_tickers_{category}")
    cached = await get_cached_data(key)
    if cached:
        return cached
    if category == "stocks":
        symbols = list(MOEX_SYMBOLS.keys())
    else:
        symbols = [k for k, v in MOEX_FUTURES.items() if v.get("cat") == category]
        if not symbols:
            symbols = list(MOEX_FUTURES.keys())
        # Тикеры фьючерсов через отдельный метод (не MOEX ISS batch для акций)
        # fetch_moex_tickers для forts использует базовый тикер — возвращаем пустой dict,
        # фронт покажет прочерки (live цены для forts через ISS marketdata ограничены)
        result = {"tickers": {}}
        await set_cached_data(key, result, ttl=60)
        return result
    try:
        tickers = await fetch_moex_tickers(symbols, category)
    except Exception:
        tickers = {}
    result = {"tickers": tickers}
    await set_cached_data(key, result, ttl=60)
    return result


@router.get("/moex/chart-data")
async def get_moex_chart_data(
    symbol: str = "SBER",
    timeframe: str = "1d",
    limit: int = 200,
    market: str = "stocks",
):
    """Комбинированный MOEX endpoint: OHLCV + все индикаторы (акции, фьючерсы, сырьё)."""
    sym = symbol.upper()
    key = get_cache_key(sym, timeframe, limit, f"moex_chart_{market}")
    cached = await get_cached_data(key)
    if cached:
        return cached
    try:
        if market == "stocks":
            df = await fetch_ohlcv_moex(sym, timeframe, limit)
        else:
            df = await fetch_ohlcv_moex_futures(sym, timeframe, limit)

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
            "symbol": sym, "timeframe": timeframe, "market": market,
            "data": ohlcv, "alligator": alligator, "ao": ao_data,
            "bwmfi": bwmfi, "fractal_highs": fractal_highs, "fractal_lows": fractal_lows,
            "bearish": bearish, "bullish": bullish, "bollinger": bollinger,
        }
        await set_cached_data(key, response, ttl=300)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MOEX chart: {str(e)}")


@router.get("/ohlcv")
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


@router.get("/alligator")
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


@router.get("/ao")
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


@router.get("/bwmfi")
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


@router.get("/fractals")
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


@router.get("/divergences")
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


def _median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _true_range(high, low, prev_close):
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


@router.get("/scan/volatile")
async def scan_volatile(threshold: float = 60.0, top: int = 20):
    """
    Сканер начала импульса (не «уже выросло», а «только начинает резко двигаться»):
    ускорение цены (return 1m/5m/15m) + аномальный относительный объём (RVOL) +
    расширение диапазона (True Range к медиане) + пробой локального 30-минутного
    диапазона. threshold — минимальный score (0-100), не процент.
    """
    key = get_cache_key("", "1m", top, f"impulse_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        all_tickers = await async_fetch_all_tickers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tickers: {str(e)}")

    # Минимальная ликвидность (volume24h уже в млн USDT) + топ по объёму
    liquid = [t for t in all_tickers.values() if t.get('volume24h', 0) >= 1.0]
    top_symbols = sorted(liquid, key=lambda t: t.get('volume24h', 0), reverse=True)[:60]

    sem = asyncio.Semaphore(6)

    async def scan_one(t_info):
        async with sem:
            try:
                sym = t_info['symbol']
                base = sym.replace('USDT', '')
                df = await async_fetch_ohlcv_df(sym, '1m', 90)
                if len(df) < 65:
                    return None

                closes = df['Close'].values
                highs = df['High'].values
                lows = df['Low'].values
                volumes = df['Volume'].values
                n = len(closes)

                def ret(k):
                    prev = closes[n - 1 - k]
                    return (closes[-1] - prev) / prev * 100 if prev else 0.0

                return_1m = ret(1)
                return_5m = ret(5)
                return_15m = ret(15)

                # RVOL: текущий объём к медиане предыдущих 60 баров
                prev_volumes = volumes[-61:-1]
                median_vol = _median(prev_volumes)
                rvol_1m = (volumes[-1] / median_vol) if median_vol > 0 else 0.0

                # Range expansion: True Range текущего бара к медиане TR предыдущих 60
                trs = [
                    _true_range(highs[i], lows[i], closes[i - 1])
                    for i in range(n - 60, n)
                ]
                current_tr = trs[-1]
                median_tr = _median(trs[:-1])
                range_expansion = (current_tr / median_tr) if median_tr > 0 else 0.0

                # z-score модуля 5-минутной доходности за последние ~60 баров
                five_min_rets = [
                    abs((closes[i] - closes[i - 5]) / closes[i - 5] * 100)
                    for i in range(n - 60, n) if closes[i - 5]
                ]
                mean_5m = sum(five_min_rets) / len(five_min_rets) if five_min_rets else 0.0
                var_5m = sum((x - mean_5m) ** 2 for x in five_min_rets) / len(five_min_rets) if five_min_rets else 0.0
                std_5m = var_5m ** 0.5
                z_abs_5m = ((abs(return_5m) - mean_5m) / std_5m) if std_5m > 0 else 0.0

                # Пробой локального диапазона (последние 30 баров, без текущего)
                window_high = max(highs[-31:-1])
                window_low = min(lows[-31:-1])
                if closes[-1] > window_high:
                    breakout = "up"
                elif closes[-1] < window_low:
                    breakout = "down"
                else:
                    breakout = "none"

                # Перегрев: движение за 15м намного больше типичного размаха
                overheat = mean_5m > 0 and abs(return_15m) > mean_5m * 6

                def clamp01(x):
                    return max(0.0, min(1.0, x))

                s_price = clamp01(max(abs(return_1m) / 2, abs(return_5m) / 5, abs(return_15m) / 8))
                s_z = clamp01(z_abs_5m / 4)
                s_rvol = clamp01(rvol_1m / 5)
                s_range = clamp01(range_expansion / 3)
                s_breakout = 1.0 if breakout != "none" else 0.0
                s_liquidity = clamp01(t_info.get('volume24h', 0) / 20)

                score = (
                    25 * s_price + 20 * s_z + 20 * s_rvol +
                    15 * s_range + 10 * s_breakout + 10 * s_liquidity
                )

                if overheat:
                    phase = "POST-PUMP"
                elif breakout == "up" and return_5m > 0:
                    phase = "UP-EXPANSION"
                elif breakout == "down" and return_5m < 0:
                    phase = "DOWN-EXPANSION"
                else:
                    phase = "HIGH-VOL-RANGE"

                if score < threshold:
                    return None

                return {
                    "symbol": sym, "name": f"{base}/USDT", "base": base,
                    "price": float(closes[-1]),
                    "return_1m": round(return_1m, 2),
                    "return_5m": round(return_5m, 2),
                    "return_15m": round(return_15m, 2),
                    "rvol_1m": round(rvol_1m, 2),
                    "range_expansion": round(range_expansion, 2),
                    "z_abs_5m": round(z_abs_5m, 2),
                    "breakout": breakout,
                    "score": round(score, 1),
                    "phase": phase,
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(t) for t in top_symbols])
    pairs = [r for r in results if r]
    pairs.sort(key=lambda x: x['score'], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=45)
    return response


@router.get("/scan/spread")
async def scan_spread(threshold: float = 1.0, top: int = 20):
    """Пары с широким спредом свечи за 15 минут (High-Low)/Low >= threshold%."""
    key = get_cache_key("", "15m", top, f"spread15_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        all_tickers = await async_fetch_all_tickers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tickers: {str(e)}")

    sorted_tickers = sorted(all_tickers.values(), key=lambda t: t.get('volume24h', 0), reverse=True)
    top_symbols = sorted_tickers[:50]

    sem = asyncio.Semaphore(6)

    async def scan_one(t_info):
        async with sem:
            try:
                sym = t_info['symbol']
                base = sym.replace('USDT', '')
                df = await async_fetch_ohlcv_df(sym, '15m', 3)
                if len(df) < 1:
                    return None
                high = float(df['High'].iloc[-1])
                low = float(df['Low'].iloc[-1])
                close = float(df['Close'].iloc[-1])
                if low <= 0:
                    return None
                spread = (high - low) / low * 100
                if spread < threshold:
                    return None
                return {
                    "symbol": sym, "name": f"{base}/USDT", "base": base,
                    "price": round(close, 8),
                    "spread": round(spread, 2),
                    "high": round(high, 8),
                    "low": round(low, 8),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(t) for t in top_symbols])
    pairs = [r for r in results if r]
    pairs.sort(key=lambda x: x['spread'], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=300)
    return response


@router.get("/chart-data")
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

        # Bollinger Bands
        df_bb = calculate_bollinger_bands(df)
        bollinger = df_bb.to_dict('records')

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
            "bollinger": bollinger,
        }
        await set_cached_data(key, response)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chart data: {str(e)}")


@router.get("/scan/divergences")
async def scan_divergences(timeframe: str = "1d", limit: int = 50):
    """Сканирует все USDT пары на дивергентный бар последнего закрытого бара."""
    cache_ttl = 3600 if timeframe in ('1d', '1w') else 900
    key = get_cache_key("scan", timeframe, limit, "scan_div")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        symbols = await async_fetch_symbols()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Symbols: {str(e)}")

    sem = asyncio.Semaphore(6)

    async def scan_one(sym_info):
        async with sem:
            try:
                df = await async_fetch_ohlcv_df(sym_info['symbol'], timeframe, limit)
                if len(df) < 10:
                    return None
                ao = calculate_ao(df)
                is_bull, is_bear = _check_last_bar_divergence(df, ao)
                if not is_bull and not is_bear:
                    return None
                return {
                    "symbol": sym_info['symbol'],
                    "name": sym_info['name'],
                    "base": sym_info['base'],
                    "type": "bull" if is_bull else "bear",
                    "close": float(df['Close'].iloc[-1]),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[scan_one(s) for s in symbols])
    divergences = [r for r in results if r]
    response = {
        "timeframe": timeframe,
        "count": len(divergences),
        "scanned": len(symbols),
        "divergences": divergences,
    }
    await set_cached_data(key, response, ttl=cache_ttl)
    return response


@router.get("/moex/scan/divergences")
async def moex_scan_divergences(timeframe: str = "1d", limit: int = 50):
    """Сканирует все MOEX инструменты (акции + фьючерсы + сырьё) на дивергентный бар."""
    cache_ttl = 3600 if timeframe in ('1d', '1w') else 900
    key = get_cache_key("moex_scan", timeframe, limit, "moex_scan_div")
    cached = await get_cached_data(key)
    if cached:
        return cached

    all_instruments = []
    for sym, meta in MOEX_SYMBOLS.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "cat": "stocks"})
    for sym, meta in MOEX_FUTURES.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "cat": meta["cat"]})

    divergences = []
    for inst in all_instruments:
        try:
            if inst["cat"] == "stocks":
                df = await fetch_ohlcv_moex(inst["symbol"], timeframe, limit)
            else:
                df = await fetch_ohlcv_moex_futures(inst["symbol"], timeframe, limit)
            if len(df) < 10:
                continue
            ao = calculate_ao(df)
            is_bull, is_bear = _check_last_bar_divergence(df, ao)
            if is_bull or is_bear:
                divergences.append({
                    "symbol": inst["symbol"],
                    "name": inst["name"],
                    "cat": inst["cat"],
                    "type": "bull" if is_bull else "bear",
                    "close": float(df["Close"].iloc[-1]),
                })
        except Exception:
            continue

    response = {
        "timeframe": timeframe,
        "count": len(divergences),
        "scanned": len(all_instruments),
        "divergences": divergences,
    }
    await set_cached_data(key, response, ttl=cache_ttl)
    return response


@router.get("/moex/scan/volatile")
async def moex_scan_volatile(threshold: float = 1.0, top: int = 20):
    """Пары MOEX с высокой волатильностью за последние 30 минут (10m свечи)."""
    key = get_cache_key("moex_vol", "10m", top, f"moex_volatile_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    all_instruments = []
    for sym, meta in MOEX_SYMBOLS.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "base": meta["base"], "cat": "stocks"})
    for sym, meta in MOEX_FUTURES.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "base": sym, "cat": meta["cat"]})

    pairs = []
    for inst in all_instruments:
        try:
            if inst["cat"] == "stocks":
                df = await fetch_ohlcv_moex(inst["symbol"], "10m", 14)
            else:
                df = await fetch_ohlcv_moex_futures(inst["symbol"], "10m", 14)
            if len(df) < 8:
                continue
            closes = df["Close"].values
            change_30m = (closes[-1] - closes[-4]) / closes[-4] * 100
            bar_changes = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
            oscillation = sum(abs(c) for c in bar_changes) / len(bar_changes)
            score = abs(change_30m) + oscillation * 3
            if abs(change_30m) < threshold:
                continue
            pairs.append({
                "symbol": inst["symbol"],
                "name": inst["name"],
                "base": inst["base"],
                "price": float(closes[-1]),
                "change_30m": round(change_30m, 2),
                "oscillation": round(oscillation, 3),
                "score": round(score, 2),
            })
        except Exception:
            continue

    pairs.sort(key=lambda x: x["score"], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=300)
    return response


@router.get("/moex/scan/spread")
async def moex_scan_spread(threshold: float = 1.0, top: int = 20):
    """MOEX инструменты с широким спредом свечи за 10 минут (High-Low)/Low >= threshold%."""
    key = get_cache_key("moex_spread", "10m", top, f"spread10_{threshold}")
    cached = await get_cached_data(key)
    if cached:
        return cached

    all_instruments = []
    for sym, meta in MOEX_SYMBOLS.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "base": meta["base"], "cat": "stocks"})
    for sym, meta in MOEX_FUTURES.items():
        all_instruments.append({"symbol": sym, "name": meta["name"], "base": sym, "cat": meta["cat"]})

    pairs = []
    for inst in all_instruments:
        try:
            if inst["cat"] == "stocks":
                df = await fetch_ohlcv_moex(inst["symbol"], "10m", 3)
            else:
                df = await fetch_ohlcv_moex_futures(inst["symbol"], "10m", 3)
            if len(df) < 1:
                continue
            high = float(df["High"].iloc[-1])
            low = float(df["Low"].iloc[-1])
            close = float(df["Close"].iloc[-1])
            if low <= 0:
                continue
            spread = (high - low) / low * 100
            if spread < threshold:
                continue
            pairs.append({
                "symbol": inst["symbol"],
                "name": inst["name"],
                "base": inst["base"],
                "price": round(close, 4),
                "spread": round(spread, 2),
                "high": round(high, 4),
                "low": round(low, 4),
            })
        except Exception:
            continue

    pairs.sort(key=lambda x: x["spread"], reverse=True)
    response = {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}
    await set_cached_data(key, response, ttl=300)
    return response


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
            await set_cached_data(key, data, ttl=30)
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
        await set_cached_data(key, result, ttl=30)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tickers: {str(e)}")
