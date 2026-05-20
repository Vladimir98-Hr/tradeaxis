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
# Обратная совместимость
MOEX_ISS_URL = MOEX_STOCKS_URL


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


async def fetch_ohlcv_moex_futures(secid: str, timeframe: str = '1d', limit: int = 100) -> pd.DataFrame:
    """
    Загружает OHLCV-свечи фьючерсов/сырья с MOEX ISS (движок forts).
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume.
    """
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
