"""
Роутер для Finam Trade API — доступен всем зарегистрированным пользователям
(токен привязан к брокерскому счёту сервиса, но используется только для чтения
публичных рыночных данных Мосбиржи — котировки и свечи, без операций со счётом).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import User
from config import FINAM_SYMBOLS, FINAM_INSTRUMENTS, FINAM_SECRET_TOKEN
from cache import get_cache_key, get_cached_data, set_cached_data, get_or_compute
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands, detect_ma_ema_signal
from finam import fetch_ohlcv_finam, fetch_finam_assets
from routes import _check_last_bar_divergence

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


def _median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _true_range(high, low, prev_close):
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


_SCAN_REFRESH_INTERVAL = 180  # фоновый цикл волатильности+EMA(15m) Finam — раз в 3 минуты
_scan_sem = asyncio.Semaphore(4)  # низкая параллельность — делим лимит Finam с остальными потребителями (чарты, живой хвост)
_FINAM_VOL_RAW_KEY = get_cache_key("finam_vol_raw", "5m", 0, "finam_impulse_raw")


async def _scan_volatile_one(inst):
    """Считает impulse-score одного инструмента без фильтра по threshold —
    отсечение по порогу теперь делается на чтении из уже готового кэша
    (см. finam_scan_volatile), а не на каждом фоновом пересчёте."""
    async with _scan_sem:
        try:
            # 90 было мало: лимит для не-deep_history запроса задаёт КАЛЕНДАРНОЕ окно
            # (end_time - 5м*(limit+5)), а не гарантированное число баров — а Мосбиржа
            # не торгует по выходным/вечерам. 900 -> окно ~3.1 календарных дня, надёжно
            # захватывает последнюю реальную торговую сессию даже после выходных
            # (тот же фикс, что уже сделан для EMA-сканера — см. _scan_ema_one).
            df = await fetch_ohlcv_finam(inst["symbol"], "5m", 900, deep_history=False)
            if len(df) < 65:
                return None

            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            volumes = df["Volume"].values
            n = len(closes)

            def ret(k):
                prev = closes[n - 1 - k]
                return (closes[-1] - prev) / prev * 100 if prev else 0.0

            return_1m = ret(1)
            return_5m = ret(3)
            return_15m = ret(6)

            prev_volumes = volumes[-61:-1]
            median_vol = _median(prev_volumes)
            rvol_1m = (volumes[-1] / median_vol) if median_vol > 0 else 0.0

            trs = [
                _true_range(highs[i], lows[i], closes[i - 1])
                for i in range(n - 60, n)
            ]
            current_tr = trs[-1]
            median_tr = _median(trs[:-1])
            range_expansion = (current_tr / median_tr) if median_tr > 0 else 0.0

            three_bar_rets = [
                abs((closes[i] - closes[i - 3]) / closes[i - 3] * 100)
                for i in range(n - 60, n) if closes[i - 3]
            ]
            mean_3b = sum(three_bar_rets) / len(three_bar_rets) if three_bar_rets else 0.0
            var_3b = sum((x - mean_3b) ** 2 for x in three_bar_rets) / len(three_bar_rets) if three_bar_rets else 0.0
            std_3b = var_3b ** 0.5
            z_abs_5m = ((abs(return_5m) - mean_3b) / std_3b) if std_3b > 0 else 0.0

            window_high = max(highs[-31:-1])
            window_low = min(lows[-31:-1])
            if closes[-1] > window_high:
                breakout = "up"
            elif closes[-1] < window_low:
                breakout = "down"
            else:
                breakout = "none"

            overheat = mean_3b > 0 and abs(return_15m) > mean_3b * 6

            def clamp01(x):
                return max(0.0, min(1.0, x))

            s_price = clamp01(max(abs(return_1m) / 2, abs(return_5m) / 5, abs(return_15m) / 8))
            s_z = clamp01(z_abs_5m / 4)
            s_rvol = clamp01(rvol_1m / 5)
            s_range = clamp01(range_expansion / 3)
            s_breakout = 1.0 if breakout != "none" else 0.0

            score = (
                25 * s_price + 20 * s_z + 20 * s_rvol +
                15 * s_range + 20 * s_breakout
            )

            if overheat:
                phase = "POST-PUMP"
            elif breakout == "up" and return_5m > 0:
                phase = "UP-EXPANSION"
            elif breakout == "down" and return_5m < 0:
                phase = "DOWN-EXPANSION"
            else:
                phase = "HIGH-VOL-RANGE"

            return {
                "symbol": inst["symbol"], "name": inst["name"], "base": inst["base"],
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


async def _compute_finam_volatile_raw() -> list:
    instruments = await _all_instruments()
    results = await asyncio.gather(*[_scan_volatile_one(inst) for inst in instruments])
    pairs = [r for r in results if r]
    pairs.sort(key=lambda x: x["score"], reverse=True)
    return pairs


@router.get("/scan/volatile")
async def finam_scan_volatile(threshold: float = 60.0, top: int = 20, current_user: User = Depends(get_current_user)):
    """
    Сканер начала импульса для Finam (аналог крипто-сканера /scan/volatile), но на
    5-минутных свечах — Finam не отдаёт минутные данные. return_1m/5m/15m здесь на
    самом деле означают 1/3/6 пятиминутных баров (~5м/15м/30м), названы так же, чтобы
    фронтенд мог переиспользовать общий рендер журнала сигналов без спец-веток.

    Сам эндпоинт только читает уже готовый результат фонового цикла
    (run_finam_scanner_refresher) и фильтрует по threshold в памяти — никаких
    обращений к Finam API на пользовательский запрос, поэтому открытие любого
    числа вкладок с автообновлением не увеличивает нагрузку на Finam.
    """
    raw = await get_cached_data(_FINAM_VOL_RAW_KEY)
    if raw is None:
        return {"threshold": threshold, "count": 0, "pairs": [], "warming_up": True}
    pairs = [p for p in raw if p["score"] >= threshold]
    return {"threshold": threshold, "count": len(pairs[:top]), "pairs": pairs[:top]}


_EMA_SCAN_TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w")
# 1h/4h/1d/1w физически не набирают 210+ реальных баров (нужных EMA200) в пределах
# одного не-deep_history запроса — Мосбиржа торгует не 24/7, а лимит там означает
# календарное окно, которое для этих ТФ упирается в потолок Finam на один запрос
# (_MAX_RANGE_DAYS). Поэтому для них используется deep_history=True (постраничная
# история) в отдельном, более медленном фоновом цикле — см. run_finam_ema_heavy_refresher.
_EMA_HEAVY_TIMEFRAMES = ("1h", "4h", "1d", "1w")


def _finam_ema_raw_key(timeframe: str) -> str:
    return get_cache_key("finam_ema_raw", timeframe, 0, "finam_ma_ema_raw")


async def _scan_ema_one(inst, timeframe: str = "15m", deep_history: bool = False):
    try:
        if deep_history:
            # limit здесь не используется (deep_history всегда отдаёт всю накопленную
            # историю по _HISTORY_DAYS в finam.py) — передаём как есть, не важно.
            df = await fetch_ohlcv_finam(inst["symbol"], timeframe, 200, deep_history=True)
        else:
            # limit здесь определяет и глубину окна запроса (end_time - 15м*(limit+5)),
            # не только число возвращаемых баров — а Мосбиржа торгует не 24/7, в отличие
            # от крипты. 900 -> окно ~9.5 календарных дней, с запасом на выходные даёт
            # ~250-300 реальных 15м-баров — хватает detect_ma_ema_signal() для EMA200,
            # не раздувая объём данных/вычислений на инструмент сильнее необходимого.
            df = await fetch_ohlcv_finam(inst["symbol"], timeframe, 900, deep_history=False)
        signal = detect_ma_ema_signal(df)
        if not signal:
            return None
        return {
            "symbol": inst["symbol"], "name": inst["name"], "base": inst["base"],
            "price": float(df["Close"].iloc[-1]),
            **signal,
        }
    except Exception:
        return None


async def _compute_finam_ema_raw_15m() -> list:
    """Быстрый путь (15m, одиночный запрос на инструмент) — часть общего быстрого
    цикла run_finam_scanner_refresher, та же логика, что и раньше."""
    instruments = await _all_instruments()

    async def one(inst):
        async with _scan_sem:
            return await _scan_ema_one(inst, "15m", deep_history=False)

    results = await asyncio.gather(*[one(inst) for inst in instruments])
    return [r for r in results if r]


async def _compute_finam_ema_raw_heavy(timeframe: str) -> list:
    """
    Тяжёлый путь для 1h/4h/1d/1w: deep_history=True (постраничная история на
    каждый инструмент). Строго последовательно по инструментам, без собственной
    параллельности сверху — пагинация внутри fetch_ohlcv_finam уже параллелит окна
    (до 6 одновременно на инструмент), а 65 инструментов разом поверх этого быстро
    утыкаются в лимит Finam (тот самый инцидент с 429, который уже было чинили).
    Тот же паттерн "один за другим с паузой", что и в _prewarm_finam_chart_cache.
    """
    instruments = await _all_instruments()
    results = []
    for inst in instruments:
        r = await _scan_ema_one(inst, timeframe, deep_history=True)
        if r:
            results.append(r)
        await asyncio.sleep(0.3)
    return results


@router.get("/scan/ema")
async def finam_scan_ma_ema(timeframe: str = "15m", top: int = 30, current_user: User = Depends(get_current_user)):
    """
    Скальпинг-сканер Finam по MA20/EMA20/50/100/200 (аналог крипто-сканера /scan/ema) —
    пересечение MA20/EMA20 и касание ценой любой из EMA20/50/100/200.
    См. indicators.detect_ma_ema_signal.

    Как и /finam/scan/volatile — только читает готовый кэш фонового цикла
    (run_finam_scanner_refresher для 15m, run_finam_ema_heavy_refresher для
    1h/4h/1d/1w), без обращений к Finam на пользовательский запрос.
    """
    if timeframe not in _EMA_SCAN_TIMEFRAMES:
        timeframe = "15m"
    raw = await get_cached_data(_finam_ema_raw_key(timeframe))
    if raw is None:
        return {"count": 0, "pairs": [], "warming_up": True}
    return {"count": len(raw[:top]), "pairs": raw[:top]}


_DIV_SCAN_TIMEFRAMES = ("15m", "1h", "4h", "1d")


def _finam_div_raw_key(timeframe: str) -> str:
    return get_cache_key("finam_div_raw", timeframe, 50, "finam_scan_div_raw")


async def _scan_div_one(inst, timeframe: str):
    async with _scan_sem:
        try:
            df = await fetch_ohlcv_finam(inst["symbol"], timeframe, 50, deep_history=False)
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


async def _compute_finam_div_raw(timeframe: str) -> dict:
    instruments = await _all_instruments()
    results = await asyncio.gather(*[_scan_div_one(inst, timeframe) for inst in instruments])
    divergences = [r for r in results if r]
    return {
        "timeframe": timeframe,
        "count": len(divergences),
        "scanned": len(instruments),
        "divergences": divergences,
    }


@router.get("/scan/divergences")
async def finam_scan_divergences(timeframe: str = "1d", limit: int = 50, current_user: User = Depends(get_current_user)):
    """
    Сканирует все инструменты Finam на дивергентный бар последнего закрытого бара.

    Раньше считалось синхронно на запрос (до ~30-40 сек на 65 инструментов) и
    делило общий лимит Finam с фоновыми циклами волатильности/EMA — под
    нагрузкой буднего дня запрос иногда не укладывался в разумное время и
    превращался в ошибку на фронте. Теперь, как и остальные Finam-сканеры,
    только читает уже готовый кэш фонового цикла (run_finam_div_refresher).
    """
    if timeframe not in _DIV_SCAN_TIMEFRAMES:
        timeframe = "1d"
    raw = await get_cached_data(_finam_div_raw_key(timeframe))
    if raw is None:
        return {"timeframe": timeframe, "count": 0, "scanned": 0, "divergences": [], "warming_up": True}
    return raw


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


async def run_finam_scanner_refresher() -> None:
    """
    Фоновый цикл: считает волатильность и MA/EMA по ВСЕМ инструментам Finam раз
    в _SCAN_REFRESH_INTERVAL и кладёт результат в кэш без фильтра по threshold/top
    — сами эндпоинты /finam/scan/volatile и /finam/scan/ema только читают этот
    кэш и фильтруют в памяти (см. выше).

    Без этого несколько открытых вкладок с автообновлением сканеров раз в
    минуту КАЖДАЯ быстро выедают лимит запросов Finam API сами на себя — именно
    так случился инцидент с массовыми 429 и зависанием сканеров на 10+ минут.
    Теперь нагрузка на Finam от этих двух сканеров фиксированная и не растёт
    с числом открытых вкладок/пользователей.
    """
    if not FINAM_SECRET_TOKEN:
        return
    await asyncio.sleep(40)  # запускаемся после каталога и прогрева графиков
    while True:
        try:
            vol_raw = await _compute_finam_volatile_raw()
            await set_cached_data(_FINAM_VOL_RAW_KEY, vol_raw, ttl=_SCAN_REFRESH_INTERVAL * 2)
        except Exception:
            pass
        await asyncio.sleep(5)  # пауза между сканерами — не бьём по Finam двумя полными обходами подряд
        try:
            ema_raw = await _compute_finam_ema_raw_15m()
            await set_cached_data(_finam_ema_raw_key("15m"), ema_raw, ttl=_SCAN_REFRESH_INTERVAL * 2)
        except Exception:
            pass
        await asyncio.sleep(_SCAN_REFRESH_INTERVAL)


async def run_finam_ema_heavy_refresher() -> None:
    """
    Фоновый цикл для EMA-сканера на 1h/4h/1d/1w — используют deep_history=True
    (постраничная история), заметно дороже быстрого 15m-пути. Считаем по одному
    таймфрейму за проход, строго последовательно по инструментам (см.
    _compute_finam_ema_raw_heavy), и по очереди обходим все 4 ТФ по кругу —
    полный оборот занимает условно 15-25 минут, чего для дневных/недельных
    сигналов более чем достаточно.
    """
    if not FINAM_SECRET_TOKEN:
        return
    await asyncio.sleep(90)  # даём быстрому циклу и прогреву графиков стартовать первыми
    while True:
        for tf in _EMA_HEAVY_TIMEFRAMES:
            try:
                raw = await _compute_finam_ema_raw_heavy(tf)
                await set_cached_data(_finam_ema_raw_key(tf), raw, ttl=40 * 60)
            except Exception:
                pass
            await asyncio.sleep(30)  # пауза между таймфреймами


async def run_finam_div_refresher() -> None:
    """
    Фоновый цикл для сканера дивергенций Finam — по кругу считает все 4
    поддерживаемых таймфрейма (15m/1h/4h/1d), каждый лёгким одиночным запросом
    на инструмент (deep_history=False, 50 баров). Дивергенция — событие
    закрытого бара, секундная свежесть не нужна, поэтому полный оборот на
    ~8-10 минут более чем достаточен, а эндпоинт /finam/scan/divergences
    всегда отвечает мгновенно из кэша, не деля ожидание ответа с остальным
    Finam-трафиком на пользовательский запрос.
    """
    if not FINAM_SECRET_TOKEN:
        return
    await asyncio.sleep(60)
    while True:
        for tf in _DIV_SCAN_TIMEFRAMES:
            try:
                raw = await _compute_finam_div_raw(tf)
                ttl = 3600 if tf == "1d" else 900
                await set_cached_data(_finam_div_raw_key(tf), raw, ttl=ttl)
            except Exception:
                pass
            await asyncio.sleep(15)  # пауза между таймфреймами
        await asyncio.sleep(5 * 60)  # пауза перед новым полным кругом
