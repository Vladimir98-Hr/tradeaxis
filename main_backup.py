from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
import ccxt
import redis.asyncio as redis
import json
import pandas as pd
import numpy as np
import hashlib
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime


app = FastAPI(title="TradingView Clone API - FULLY WORKING")
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["http://localhost:3000", "http://localhost:8000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.from_url("redis://localhost:6379", encoding="utf-8", decode_responses=True)
bybit = ccxt.bybit({'apiKey': '', 'secret': '', 'sandbox': False})

@app.on_event("startup")
async def startup():
    await FastAPILimiter.init(redis_client)

# 🔥 Bybit форматы
BYBIT_TIMEFRAMES = {
    '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', 
    '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '12h': '12h',
    '1d': '1d', '1w': '1w'
}

def normalize_symbol(symbol: str) -> str:
    return symbol.replace('/', '').upper()

def normalize_timeframe(timeframe: str) -> str:
    return BYBIT_TIMEFRAMES.get(timeframe.lower(), timeframe)

def get_cache_key(symbol: str, timeframe: str, limit: int, endpoint: str) -> str:
    key_string = f"{endpoint}:{symbol}:{timeframe}:{limit}"
    return hashlib.md5(key_string.encode()).hexdigest()

async def get_cached_data(key: str):
    data = await redis_client.get(key)
    if data:
        return json.loads(data)
    return None

async def set_cached_data(key: str, data: dict, ttl: int = 300):
    await redis_client.setex(key, ttl, json.dumps(data))

def fetch_ohlcv_df(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    bybit_symbol = normalize_symbol(symbol)  # BTCUSDT
    bybit_timeframe = normalize_timeframe(timeframe)  # 1h
    
    print(f"🔥 Bybit: {bybit_symbol} {bybit_timeframe} limit={limit}")
    
    ohlcv = bybit.fetch_ohlcv(bybit_symbol, bybit_timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d %H:%M:%S')
    df = df.astype({'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float})
    return df

def smma(data: np.ndarray, period: int) -> np.ndarray:
    if len(data) < period:
        return np.full(len(data), 0.0)
    
    smma_vals = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        smma_vals.append((smma_vals[-1] * (period - 1) + data[i]) / period)
    
    result = np.full(len(data), 0.0)
    result[period-1:period-1+len(smma_vals)] = smma_vals
    return result

def calculate_alligator(df: pd.DataFrame) -> pd.DataFrame:
    hl2 = (df['High'] + df['Low']) / 2
    jaw = smma(hl2.values, 13)
    teeth = smma(hl2.values, 8)
    lips = smma(hl2.values, 5)
    
    df_alligator = df[['timestamp', 'Close']].copy()
    df_alligator['Jaw'] = jaw
    df_alligator['Teeth'] = teeth
    df_alligator['Lips'] = lips
    return df_alligator.fillna(0)

def calculate_ao(df: pd.DataFrame) -> pd.Series:
    hl2 = (df['High'] + df['Low']) / 2
    ao = hl2.rolling(window=5).mean() - hl2.rolling(window=34).mean()
    return ao.fillna(0)

def calculate_bw_mfi(df: pd.DataFrame, color_style: bool = False):
    mfi = np.zeros(len(df))
    for i in range(1, len(df)):
        if df['Volume'].iloc[i] > 0:
            mfi[i] = (df['High'].iloc[i] - df['Low'].iloc[i]) / df['Volume'].iloc[i]
    
    palette = ['#000000'] * len(df)
    for i in range(1, len(df)):
        vol_curr, vol_prev = df['Volume'].iloc[i], df['Volume'].iloc[i-1]
        mfi_curr, mfi_prev = mfi[i], mfi[i-1]
        
        if vol_curr < vol_prev and mfi_curr < mfi_prev:
            palette[i] = '#795548' if not color_style else '#9E9E9E'
        elif vol_curr < vol_prev and mfi_curr >= mfi_prev:
            palette[i] = '#03A9F4' if not color_style else '#E53935'
        elif vol_curr >= vol_prev and mfi_curr < mfi_prev:
            palette[i] = '#E91E63' if not color_style else '#00897B'
        elif vol_curr >= vol_prev and mfi_curr >= mfi_prev:
            palette[i] = '#8BC34A' if not color_style else '#00897B'
    
    return pd.Series(mfi), palette

@app.get("/health")
async def health():
    return {"status": "🚀 TradingView Clone API - Все индикаторы работают!"}

@app.get("/ohlcv", dependencies=[Depends(RateLimiter(times=60, seconds=60))])
async def get_ohlcv(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 100):
    key = get_cache_key(symbol, timeframe, limit, "ohlcv")
    cached = await get_cached_data(key)
    if cached: return {"cached": True, **cached}
    
    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        result = df.to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "data": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bybit: {str(e)}")

@app.get("/alligator", dependencies=[Depends(RateLimiter(times=60, seconds=60))])
async def get_alligator(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    key = get_cache_key(symbol, timeframe, limit, "alligator")
    cached = await get_cached_data(key)
    if cached: return {"cached": True, **cached}
    
    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        df_alligator = calculate_alligator(df)
        result = df_alligator.tail(100).to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "alligator": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alligator: {str(e)}")

@app.get("/ao", dependencies=[Depends(RateLimiter(times=60, seconds=60))])
async def get_ao(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200):
    key = get_cache_key(symbol, timeframe, limit, "ao")
    cached = await get_cached_data(key)
    if cached: return {"cached": True, **cached}
    
    try:
        df = fetch_ohlcv_df(symbol, timeframe, limit)
        ao = calculate_ao(df)
        df_ao = pd.DataFrame({
            'timestamp': df['timestamp'], 
            'AO': ao.values
        })
        result = df_ao.tail(100).to_dict('records')
        response = {"symbol": symbol, "timeframe": timeframe, "count": len(result), "ao": result}
        await set_cached_data(key, response)
        return {"cached": False, **response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AO: {str(e)}")

@app.get("/bwmfi", dependencies=[Depends(RateLimiter(times=60, seconds=60))])
async def get_bwmfi(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 200, color_style: bool = False):
    key = get_cache_key(symbol, timeframe, limit, f"bwmfi_{color_style}")
    cached = await get_cached_data(key)
    if cached: return {"cached": True, **cached}
    
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

# 🔥 WebSocket LIVE ТИКЕРЫ
@app.websocket("/ws/{symbol}")
async def websocket_live(websocket: WebSocket, symbol: str = "BTCUSDT"):
    await websocket.accept()
    print(f"🔥 WebSocket подключен: {symbol}")
    
    try:
        while True:
            try:
                # LIVE данные с Bybit (каждую секунду)
                ticker = bybit.fetch_ticker(normalize_symbol(symbol))
                
                live_data = {
                    "symbol": symbol,
                    "price": round(ticker['last'], 2),
                    "change24h": round(ticker['percentage'], 2),
                    "high24h": round(ticker['high'], 2),
                    "low24h": round(ticker['low'], 2),
                    "volume24h": round(ticker['quoteVolume'] / 1_000_000, 2),  # В миллионах
                    "timestamp": datetime.now().strftime('%H:%M:%S')
                }
                
                await websocket.send_json(live_data)
                print(f"📡 Отправили: {live_data['price']}")
                
            except Exception as e:
                error_data = {"error": str(e), "timestamp": datetime.now().strftime('%H:%M:%S')}
                await websocket.send_json(error_data)
            
            await asyncio.sleep(1)  # 1 секунда интервал
    
    except WebSocketDisconnect:
        print(f"❌ WebSocket отключен: {symbol}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
