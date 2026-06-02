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

# Разрешенные CORS-источники (берём из .env через запятую)
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:8000")
CORS_ORIGINS = [s.strip() for s in _cors_raw.split(",")]

# Время жизни кеша в секундах (по умолчанию 5 минут)
CACHE_TTL = 300

# Настройки rate-limiter (запросов / секунд)
RATE_LIMIT_TIMES = 60
RATE_LIMIT_SECONDS = 60

# Хост и порт сервера
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Настройки аутентификации (JWT)
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-please")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

# База данных пользователей (SQLite)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./users.db")

# Акции MOEX (через MOEX ISS API, без токена, борд TQBR)
MOEX_SYMBOLS = {
    "SBER":  {"name": "SBER / Сбербанк",      "base": "SBER"},
    "GAZP":  {"name": "GAZP / Газпром",        "base": "GAZP"},
    "LKOH":  {"name": "LKOH / Лукойл",        "base": "LKOH"},
    "YDEX":  {"name": "YDEX / Яндекс",        "base": "YDEX"},
    "NVTK":  {"name": "NVTK / Новатэк",       "base": "NVTK"},
    "ROSN":  {"name": "ROSN / Роснефть",      "base": "ROSN"},
    "GMKN":  {"name": "GMKN / Норникель",     "base": "GMKN"},
    "MTSS":  {"name": "MTSS / МТС",           "base": "MTSS"},
    "SBERP": {"name": "SBERP / Сбербанк п",   "base": "SBERP"},
    "VTBR":  {"name": "VTBR / ВТБ",           "base": "VTBR"},
    "MGNT":  {"name": "MGNT / Магнит",        "base": "MGNT"},
    "TATN":  {"name": "TATN / Татнефть",      "base": "TATN"},
    "ALRS":  {"name": "ALRS / Алроса",        "base": "ALRS"},
    "PLZL":  {"name": "PLZL / Полюс",         "base": "PLZL"},
    "MOEX":  {"name": "MOEX / Московская биржа", "base": "MOEX"},
}

# Фьючерсы и сырьё MOEX — базовые тикеры.
# Конкретный контракт (SiM6, BRM6...) определяется автоматически в moex.get_active_future_secid().
MOEX_FUTURES = {
    # Фьючерсы (cat=futures)
    "Si": {"name": "Si / USD-RUB",       "cat": "futures"},
    "Ri": {"name": "Ri / Индекс РТС",    "cat": "futures"},
    "MX": {"name": "MX / Индекс МосБ",   "cat": "futures"},
    "Eu": {"name": "Eu / EUR-RUB",        "cat": "futures"},
    # Сырьё (cat=commodities)
    "BR": {"name": "BR / Нефть Brent",   "cat": "commodities"},
    "GD": {"name": "GD / Золото",         "cat": "commodities"},
    "SV": {"name": "SV / Серебро",        "cat": "commodities"},
    "NG": {"name": "NG / Природный газ",  "cat": "commodities"},
}
