"""
Модуль WebSocket для потоковой передачи данных тикера в реальном времени.
Подключается к бирже и отправляет обновления цены каждую секунду.
"""

import asyncio
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from exchange import exchange, normalize_symbol

# Маршрутизатор для WebSocket
router = APIRouter()


@router.websocket("/ws/{symbol}")
async def websocket_live(websocket: WebSocket, symbol: str = "BTCUSDT"):
    """
    WebSocket-эндпоинт для получения live-данных тикера.
    Отправляет: цену, изменение за 24ч, максимум/минимум, объем.
    Интервал обновления - 1 секунда.
    """
    await websocket.accept()
    print(f"WebSocket подключен: {symbol}")

    try:
        while True:
            try:
                # Получаем актуальные данные тикера с биржи
                ticker = exchange.fetch_ticker(normalize_symbol(symbol))

                live_data = {
                    "symbol": symbol,
                    "price": round(ticker['last'], 2),
                    "change24h": round(ticker['percentage'], 2),
                    "high24h": round(ticker['high'], 2),
                    "low24h": round(ticker['low'], 2),
                    "volume24h": round(ticker['quoteVolume'] / 1_000_000, 2),
                    "timestamp": datetime.now().strftime('%H:%M:%S')
                }

                await websocket.send_json(live_data)

            except Exception as e:
                error_data = {"error": str(e), "timestamp": datetime.now().strftime('%H:%M:%S')}
                await websocket.send_json(error_data)

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        print(f"WebSocket отключен: {symbol}")
