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
app.include_router(api_router)
app.include_router(ws_router)

# Раздача статических файлов (фронтенд)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    """Отдает главную HTML-страницу фронтенда."""
    return FileResponse("static/index.html")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
