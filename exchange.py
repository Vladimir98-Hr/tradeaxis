"""
Модуль работы с биржей.
Содержит подключение через ccxt, нормализацию символов/таймфреймов
и функцию загрузки OHLCV-данных.
Биржа задается в config.py (EXCHANGE_ID).
"""

import asyncio
import ccxt
import pandas as pd
from config import EXCHANGE_ID, EXCHANGE_TIMEFRAMES

# Создаем клиент биржи через ccxt (публичный доступ, без ключей)
exchange = getattr(ccxt, EXCHANGE_ID)()


def fetch_symbols() -> list:
    """Загрузить доступные USDT spot-пары с биржи."""
    exchange.load_markets()
    symbols = []
    for sym, market in exchange.markets.items():
        if market.get('quote') == 'USDT' and market.get('spot'):
            symbols.append({
                'symbol': market['base'] + 'USDT',
                'name': sym,
                'base': market['base'],
            })
    symbols.sort(key=lambda x: x['base'])
    return symbols


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


def fetch_ticker(symbol: str) -> dict:
    """Получает текущую цену и 24ч статистику с биржи."""
    ex_symbol = normalize_symbol(symbol)
    ticker = exchange.fetch_ticker(ex_symbol)
    return {
        "symbol": symbol,
        "price": round(ticker['last'], 8),
        "change24h": round(ticker.get('percentage') or 0, 2),
        "high24h": round(ticker.get('high') or 0, 8),
        "low24h": round(ticker.get('low') or 0, 8),
        "volume24h": round((ticker.get('quoteVolume') or 0) / 1_000_000, 2),
    }


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


def fetch_all_tickers() -> dict:
    """Все USDT spot тикеры одним вызовом к бирже."""
    tickers = exchange.fetch_tickers(params={'instType': 'SPOT'})
    result = {}
    for sym, t in tickers.items():
        if '/USDT' in sym:
            base = sym.replace('/USDT', '')
            result[base + 'USDT'] = {
                "symbol": base + 'USDT',
                "price": round(t['last'] or 0, 8),
                "change24h": round(t.get('percentage') or 0, 2),
                "high24h": round(t.get('high') or 0, 8),
                "low24h": round(t.get('low') or 0, 8),
                "volume24h": round((t.get('quoteVolume') or 0) / 1_000_000, 2),
            }
    return result


# Async-обёртки: ccxt синхронный, to_thread() не блокирует event loop FastAPI
async def async_fetch_ohlcv_df(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    return await asyncio.to_thread(fetch_ohlcv_df, symbol, timeframe, limit)

async def async_fetch_ticker(symbol: str) -> dict:
    return await asyncio.to_thread(fetch_ticker, symbol)

async def async_fetch_symbols() -> list:
    return await asyncio.to_thread(fetch_symbols)

async def async_fetch_all_tickers() -> dict:
    return await asyncio.to_thread(fetch_all_tickers)
