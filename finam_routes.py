"""
Роутер для Finam Trade API — доступен всем зарегистрированным пользователям
(токен привязан к брокерскому счёту сервиса, но используется только для чтения
публичных рыночных данных Мосбиржи — котировки и свечи, без операций со счётом).
"""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import User
from config import FINAM_SYMBOLS, FINAM_INSTRUMENTS, FINAM_SECRET_TOKEN
from cache import get_cache_key, get_cached_data, set_cached_data, get_or_compute
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands
from finam import fetch_ohlcv_finam, fetch_finam_assets

router = APIRouter(prefix="/finam", tags=["finam"])


def _curated_instruments(category: str) -> list:
    """Curated-список инструментов Finam из config.py по категории."""
    if category == "stocks":
        return [
            {"symbol": f"{k}@MISX", "name": v["name"], "base": v["base"], "cat": "stocks",
             "currency": v.get("currency"), "point_based": v.get("point_based", False)}
            for k, v in FINAM_SYMBOLS.items()
        ]
    return [
        {"symbol": k, "name": v["name"], "base": k.split("@")[0], "cat": v["cat"],
         "currency": v.get("currency"), "point_based": v.get("point_based", False)}
        for k, v in FINAM_INSTRUMENTS.items()
        if v["cat"] == category
    ]


# Живое расширение поверх curated-списка включаем только там, где категория
# однозначно определяется одной биржей Finam (mic), иначе типы пересекаются:
# - currencies/commodities у Finam оба размечены типом CURRENCIES;
# - товарные/индексные/облигационные мировые фьючерсы делят одни и те же биржи
#   (например XCBT — и пшеница, и облигации США), их разделяет только curated-список.
# stocks (акции Мосбиржи, MISX) и futures (фьючерсы Мосбиржи, RTSX) — безопасны.
_LIVE_EXTENSION_TYPE_MIC = {"stocks": ("EQUITIES", "MISX"), "futures": ("FUTURES", "RTSX")}


async def _category_instruments(category: str) -> list:
    """
    Инструменты Finam по категории: сначала проверенный curated-список из config.py
    (гарантированно рабочий), затем расширяем живым каталогом /v1/assets/all —
    если Finam недоступен или категория не поддерживает безопасное расширение,
    тихо остаёмся на curated-only.
    """
    curated = _curated_instruments(category)
    curated_symbols = {c["symbol"] for c in curated}

    extra = []
    try:
        wanted = _LIVE_EXTENSION_TYPE_MIC.get(category)
        if wanted:
            wanted_type, wanted_mic = wanted
            assets = await fetch_finam_assets()
            for a in assets:
                sym = a.get("symbol")
                if not sym or sym in curated_symbols:
                    continue
                if a.get("type") != wanted_type or a.get("mic") != wanted_mic:
                    continue
                # Живой каталог Finam не содержит валюту/тип цены — для акций MISX
                # это всегда рублёвый спот, для фьючерсов RTSX — точечная цена без
                # известной валюты/стоимости пункта (вводится вручную в калькуляторе).
                if category == "stocks":
                    currency, point_based = "RUB", False
                else:
                    currency, point_based = None, True
                extra.append({"symbol": sym, "name": a.get("name") or sym, "base": a.get("ticker", sym), "cat": category,
                               "currency": currency, "point_based": point_based})
    except HTTPException:
        pass

    return curated + extra


@router.get("/symbols")
async def get_finam_symbols(category: str = "stocks", current_user: User = Depends(get_current_user)):
    """Список инструментов Finam по категории: stocks | futures | currencies | commodities."""
    return {"category": category, "symbols": await _category_instruments(category)}


async def _build_finam_chart_data(symbol: str, timeframe: str, limit: int, deep_history: bool = True) -> dict:
    """
    Собирает ответ /finam/chart-data (OHLCV + индикаторы) без обращения к кешу —
    переиспользуется и самим эндпоинтом, и фоновым прогревом кеша.
    """
    df = await fetch_ohlcv_finam(symbol, timeframe, limit, deep_history=deep_history)

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

    return {
        "symbol": symbol, "timeframe": timeframe,
        "data": ohlcv, "alligator": alligator, "ao": ao_data,
        "bwmfi": bwmfi, "fractal_highs": fractal_highs, "fractal_lows": fractal_lows,
        "bearish": bearish, "bullish": bullish, "bollinger": bollinger,
    }


def _finam_chart_ttl(timeframe: str) -> int:
    # Глубокая история (1d/1w) собирается несколькими параллельными запросами
    # к Finam и почти не меняется в течение дня — держим в кеше дольше,
    # чтобы повторные открытия графика были мгновенными.
    return 3600 * 3 if timeframe in ('1d', '1w') else 300


@router.get("/chart-data")
async def get_finam_chart_data(
    symbol: str = "SBER@MISX",
    timeframe: str = "1d",
    limit: int = 200,
    deep_history: bool = True,
    current_user: User = Depends(get_current_user),
):
    """
    Комбинированный Finam endpoint: OHLCV + все индикаторы.
    deep_history=false — лёгкий одиночный запрос на последние ~limit баров без
    постраничной загрузки всей истории; используется фронтом для частого
    живого доопроса хвоста графика (см. refreshLiveTail), чтобы не повторять
    тяжёлую пагинацию при каждом обновлении.
    """
    key = get_cache_key(symbol, timeframe, limit, f"finam_chart_{deep_history}")
    ttl = _finam_chart_ttl(timeframe) if deep_history else 15

    async def compute():
        return await _build_finam_chart_data(symbol, timeframe, limit, deep_history=deep_history)

    try:
        return await get_or_compute(key, compute, ttl=ttl)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finam chart: {str(e)}")


_ALL_CATEGORIES = ("stocks", "futures", "currencies", "commodities")


async def _all_instruments() -> list:
    """
    Все инструменты Finam для сканеров: curated-список из config.py + живое
    расширение из полного каталога /v1/assets/all (акции MISX, фьючерсы RTSX) —
    та же логика, что и в /finam/symbols, объединённая по всем категориям сразу.
    """
    per_category = await asyncio.gather(*[_category_instruments(c) for c in _ALL_CATEGORIES])
    instruments = []
    for group in per_category:
        instruments.extend(group)
    return instruments


# Прогреваем кеш только для дневного/недельного графика — они самые тяжёлые при
# холодной загрузке (несколько параллельных запросов к Finam) и при этом самые
# дешёвые по частоте: TTL 3ч, обновлять чаще нет смысла. Внутридневные ТФ
# оставляем на ленивую загрузку — не хотим грузить и без того тесный VPS.
_PREWARM_TIMEFRAMES = ("1d", "1w")
_PREWARM_LIMIT = 200  # совпадает с дефолтным chartLimit фронтенда — иначе кеш не попадёт


async def _prewarm_finam_chart_cache() -> None:
    """
    Прогревает кеш /finam/chart-data для курируемого списка инструментов на 1d/1w,
    чтобы первое открытие графика у пользователя уже брало данные из кеша, а не
    ждало живого запроса к Finam. Строго последовательно (один запрос за раз, с
    паузой) — сервер работает на тесном VPS, широкая параллельность тут неуместна.
    """
    instruments = []
    for category in _ALL_CATEGORIES:
        instruments.extend(_curated_instruments(category))

    for inst in instruments:
        symbol = inst["symbol"]
        for timeframe in _PREWARM_TIMEFRAMES:
            key = get_cache_key(symbol, timeframe, _PREWARM_LIMIT, "finam_chart")
            if await get_cached_data(key):
                continue  # уже тёплый — не тратим лишний запрос
            try:
                response = await _build_finam_chart_data(symbol, timeframe, _PREWARM_LIMIT)
                await set_cached_data(key, response, ttl=_finam_chart_ttl(timeframe))
            except Exception:
                pass
            await asyncio.sleep(0.3)


async def run_finam_chart_prewarmer() -> None:
    """Фоновый цикл: прогревает кеш графиков Finam при старте и затем каждые ~2.5ч (до истечения 3ч TTL)."""
    if not FINAM_SECRET_TOKEN:
        return
    await asyncio.sleep(15)  # даём приложению спокойно подняться перед фоновой нагрузкой
    while True:
        try:
            await _prewarm_finam_chart_cache()
        except Exception:
            pass
        await asyncio.sleep(2.5 * 3600)


