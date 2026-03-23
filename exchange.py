"""
Модуль работы с биржей.
Содержит подключение через ccxt, нормализацию символов/таймфреймов
и функцию загрузки OHLCV-данных.
Биржа задается в config.py (EXCHANGE_ID).
"""

import ccxt
import pandas as pd
from config import EXCHANGE_ID, EXCHANGE_TIMEFRAMES

# Создаем клиент биржи через ccxt (публичный доступ, без ключей)
exchange = getattr(ccxt, EXCHANGE_ID)()


def normalize_symbol(symbol: str) -> str:
    """Нормализует символ торговой пары (убирает '/', приводит к верхнему регистру)."""
    s = symbol.replace('/', '').upper()
    # Для ccxt нужен формат с '/' (например BTC/USDT)
    if '/' not in symbol and 'USDT' in s:
        base = s.replace('USDT', '')
        return f"{base}/USDT"
    return symbol.upper()


def normalize_timeframe(timeframe: str) -> str:
    """Нормализует таймфрейм в формат, поддерживаемый биржей."""
    return EXCHANGE_TIMEFRAMES.get(timeframe.lower(), timeframe)


def fetch_ohlcv_df(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Загружает OHLCV-данные (свечи) с биржи.
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume.
    """
    ex_symbol = normalize_symbol(symbol)
    ex_timeframe = normalize_timeframe(timeframe)

    print(f"{EXCHANGE_ID}: {ex_symbol} {ex_timeframe} limit={limit}")

    ohlcv = exchange.fetch_ohlcv(ex_symbol, ex_timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d %H:%M:%S')
    df = df.astype({'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float})
    return df
