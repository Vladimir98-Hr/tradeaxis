"""
Модуль конфигурации приложения.
Содержит все настройки, константы и параметры подключения.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# URL подключения к Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Настройки биржи (публичный доступ, ключи не требуются для рыночных данных)
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "okx")  # Биржа: okx, binance, bybit, kraken и т.д.

# Разрешенные таймфреймы (ключ - пользовательский формат, значение - формат биржи)
EXCHANGE_TIMEFRAMES = {
    '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
    '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '12h': '12h',
    '1d': '1d', '1w': '1w'
}

# Разрешенные CORS-источники
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]

# Время жизни кеша в секундах (по умолчанию 5 минут)
CACHE_TTL = 300

# Настройки rate-limiter (запросов / секунд)
RATE_LIMIT_TIMES = 60
RATE_LIMIT_SECONDS = 60

# Хост и порт сервера
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
