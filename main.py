"""
Главный модуль приложения TradingView Clone API.
Создает FastAPI-приложение, подключает middleware, маршруты и раздачу статики.
Запуск: python main.py
"""

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from config import CORS_ORIGINS, HOST, PORT
from routes import router as api_router
from websocket import router as ws_router
from auth_routes import router as auth_router
from user_routes import router as user_router
from chat import router as chat_router
from news_routes import router as news_router
from database import init_db

# Создание приложения
app = FastAPI(title="TradingView Clone API")

# Настройка CORS (разрешенные источники)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение маршрутов REST API и WebSocket
# chat_router должен быть до ws_router, иначе /ws/{symbol} перехватит /ws/chat
app.include_router(chat_router)
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(news_router)


async def _warm_cache():
    """Прогрев Redis кэша после старта — тикеры и главный чарт грузятся заранее."""
    await asyncio.sleep(3)
    try:
        from exchange import async_fetch_all_tickers, async_fetch_ohlcv_df
        from cache import get_cache_key, set_cached_data
        from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands
        # Прогрев тикеров
        data = await async_fetch_all_tickers()
        key = get_cache_key("", "", 0, "tickers_all")
        await set_cached_data(key, {"tickers": data}, ttl=30)
        # Прогрев главного чарта BTC/USDT 1h
        df = await async_fetch_ohlcv_df("BTCUSDT", "1h", 200)
        if df is not None and not df.empty:
            alligator = calculate_alligator(df)
            ao = calculate_ao(df)
            bwmfi = calculate_bw_mfi(df)
            fractals = find_fractals(df)
            divergences = find_divergences(df)
            bb = calculate_bollinger_bands(df)
            result = {
                "ohlcv": df[["timestamp","open","high","low","close","volume"]].tail(200).to_dict("records"),
                "alligator": alligator, "ao": ao, "bwmfi": bwmfi,
                "fractals": fractals, "divergences": divergences, "bollinger": bb,
            }
            chart_key = get_cache_key("BTCUSDT", "1h", 200, "chart_data")
            await set_cached_data(chart_key, result, ttl=300)
    except Exception:
        pass


@app.on_event("startup")
async def startup():
    """Инициализация БД при запуске приложения."""
    import os
    os.makedirs("uploads/news", exist_ok=True)
    await init_db()
    asyncio.create_task(_warm_cache())

# Создаём папку uploads заранее (StaticFiles требует существующую директорию)
import os as _os
_os.makedirs("uploads/news", exist_ok=True)

# Раздача загруженных файлов (фото, аудио, документы для журнала автора)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Раздача статических файлов (фронтенд)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    """Отдает главную HTML-страницу фронтенда."""
    return FileResponse("static/index.html")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
