"""
Модуль для получения данных Московской биржи через публичное API MOEX ISS.
Не требует токена или регистрации.
"""

import httpx
import pandas as pd
from datetime import datetime, timedelta

# Таймфреймы MOEX ISS: наш формат → числовой код интервала
MOEX_TIMEFRAMES = {
    '1m': 1,
    '10m': 10,
    '1h': 60,
    '1d': 24,
    '1w': 7,
}

# Длительность одного бара для вычисления диапазона дат
_INTERVAL_DELTA = {
    1: timedelta(minutes=1),
    10: timedelta(minutes=10),
    60: timedelta(hours=1),
    24: timedelta(days=1),
    7: timedelta(weeks=1),
}

MOEX_STOCKS_URL  = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{symbol}/candles.json"
MOEX_FUTURES_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{symbol}/candles.json"
MOEX_FORTS_SECURITIES_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json"
# Обратная совместимость
MOEX_ISS_URL = MOEX_STOCKS_URL

# Кэш активных контрактов: base → (secid, expires_at)
_futures_cache: dict = {}


async def get_active_future_secid(base: str) -> str:
    """
    Возвращает SECID ближайшего активного фьючерса для базового тикера (Si, BR, GD...).
    Автоматически обходит истёкшие контракты. Кешируется в памяти на 4 часа.
    """
    now = datetime.now()
    if base in _futures_cache:
        secid, expires_at = _futures_cache[base]
        if now < expires_at:
            return secid

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(MOEX_FORTS_SECURITIES_URL, params={"iss.meta": "off"})
        resp.raise_for_status()
        data = resp.json()

    cols = data["securities"]["columns"]
    rows = data["securities"]["data"]
    # Буфер 3 дня — за 3 дня до экспирации объём падает, берём следующий контракт
    cutoff = (now + timedelta(days=3)).date()
    candidates = []
    for row in rows:
        r = dict(zip(cols, row))
        secid = r.get("SECID", "")
        last_trade = r.get("LASTTRADEDATE")
        if not secid.upper().startswith(base.upper()):
            continue
        if last_trade:
            exp = datetime.strptime(last_trade, "%Y-%m-%d").date()
            if exp >= cutoff:
                candidates.append((exp, secid))

    if not candidates:
        raise ValueError(f"Нет активных фьючерсов для базового актива {base!r}")

    candidates.sort()
    result = candidates[0][1]
    _futures_cache[base] = (result, now + timedelta(hours=4))
    return result


async def fetch_ohlcv_moex(symbol: str, timeframe: str = '1d', limit: int = 100) -> pd.DataFrame:
    """
    Загружает OHLCV-свечи с MOEX ISS для указанного тикера.
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume.
    """
    interval = MOEX_TIMEFRAMES.get(timeframe, 24)
    delta = _INTERVAL_DELTA.get(interval, timedelta(days=1))

    till = datetime.now()
    from_ = till - delta * (limit + 5)  # небольшой запас

    params = {
        'interval': interval,
        'from': from_.strftime('%Y-%m-%d'),
        'till': till.strftime('%Y-%m-%d %H:%M:%S'),
    }

    url = MOEX_ISS_URL.format(symbol=symbol.upper())

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    candles = data.get('candles', {})
    columns = candles.get('columns', [])
    rows = candles.get('data', [])

    if not rows:
        raise ValueError(f"MOEX ISS: нет данных для {symbol} ({timeframe})")

    df = pd.DataFrame(rows, columns=columns)

    # Приводим к стандартному формату
    result = pd.DataFrame({
        'timestamp': pd.to_datetime(df['begin']).dt.strftime('%Y-%m-%d %H:%M:%S'),
        'Open': df['open'].astype(float),
        'High': df['high'].astype(float),
        'Low': df['low'].astype(float),
        'Close': df['close'].astype(float),
        'Volume': df['volume'].astype(float),
    })

    return result.tail(limit).reset_index(drop=True)


async def fetch_ohlcv_moex_futures(base: str, timeframe: str = '1d', limit: int = 100) -> pd.DataFrame:
    """
    Загружает OHLCV-свечи фьючерсов/сырья с MOEX ISS (движок forts).
    Принимает базовый тикер (Si, BR, GD...) и автоматически определяет
    текущий активный контракт (SiM6, BRM6...) через get_active_future_secid().
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume.
    """
    secid = await get_active_future_secid(base)

    interval = MOEX_TIMEFRAMES.get(timeframe, 24)
    delta = _INTERVAL_DELTA.get(interval, timedelta(days=1))

    till = datetime.now()
    from_ = till - delta * (limit + 5)

    params = {
        'interval': interval,
        'from': from_.strftime('%Y-%m-%d'),
        'till': till.strftime('%Y-%m-%d %H:%M:%S'),
    }

    url = MOEX_FUTURES_URL.format(symbol=secid.upper())

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    candles = data.get('candles', {})
    columns = candles.get('columns', [])
    rows = candles.get('data', [])

    if not rows:
        raise ValueError(f"MOEX ISS forts: нет данных для {secid} ({timeframe})")

    df = pd.DataFrame(rows, columns=columns)

    result = pd.DataFrame({
        'timestamp': pd.to_datetime(df['begin']).dt.strftime('%Y-%m-%d %H:%M:%S'),
        'Open':   df['open'].astype(float),
        'High':   df['high'].astype(float),
        'Low':    df['low'].astype(float),
        'Close':  df['close'].astype(float),
        'Volume': df['volume'].astype(float),
    })

    return result.tail(limit).reset_index(drop=True)


async def fetch_moex_tickers(symbols: list, category: str = "stocks") -> dict:
    """
    Возвращает текущие рыночные данные для списка инструментов MOEX одним запросом.
    """
    if category == "stocks":
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
    else:
        url = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json"

    params = {"securities": ",".join(symbols), "iss.meta": "off"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    # Из блока securities берём PREVPRICE (цена предыдущего закрытия — всегда есть)
    sec_block = data.get("securities", {})
    sec_cols = sec_block.get("columns", [])
    sec_rows = sec_block.get("data", [])
    prev_prices = {}
    for row in sec_rows:
        r = dict(zip(sec_cols, row))
        secid = r.get("SECID")
        if not secid:
            continue
        for field in ("PREVPRICE", "PREVLEGALCLOSEPRICE", "PREVADMITTEDQUOTE"):
            if r.get(field) is not None:
                prev_prices[secid] = r[field]
                break

    # Из блока marketdata берём живые данные (LAST может быть null вне торговой сессии)
    md = data.get("marketdata", {})
    cols = md.get("columns", [])
    rows = md.get("data", [])
    result = {}
    for row in rows:
        r = dict(zip(cols, row))
        secid = r.get("SECID")
        if not secid:
            continue
        price = r.get("LAST") or prev_prices.get(secid)
        if price is None:
            continue
        result[secid] = {
            "price": price,
            "change": round(r.get("LASTTOPREVPRICE") or 0, 2),
            "high": r.get("HIGH"),
            "low": r.get("LOW"),
            "volume": r.get("VOLUME"),
        }
    return result
