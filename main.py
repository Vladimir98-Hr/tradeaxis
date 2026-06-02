"""
Главный модуль приложения TradingView Clone API.
Создает FastAPI-приложение, подключает middleware, маршруты и раздачу статики.
Запуск: python main.py
"""

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


@app.on_event("startup")
async def startup():
    """Инициализация БД при запуске приложения."""
    import os
    os.makedirs("uploads/news", exist_ok=True)
    await init_db()

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
