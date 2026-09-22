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

# Настройки почты (для восстановления пароля). Пусто = письма не отправляются, только логируются.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

# Публичный адрес фронтенда — используется в ссылке сброса пароля
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")

# Время жизни токена сброса пароля (минуты)
RESET_TOKEN_EXPIRE_MINUTES = 60

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

# Finam Trade API — secret-токен из личного кабинета Финама, раздел «Токены».
# Пусто = раздел Finam в терминале недоступен. Доступен всем зарегистрированным пользователям.
FINAM_SECRET_TOKEN = os.getenv("FINAM_SECRET_TOKEN", "")

# Акции Finam (те же эмитенты MOEX, но тикеры в формате TICKER@MISX для Finam Trade API)
FINAM_SYMBOLS = {
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

# Фьючерсы, валюты и сырьё Finam. symbol — точный тикер в формате Finam (TICKER@MIC),
# подтверждён живым запросом к /v1/assets/all и /v1/instruments/{symbol}/bars.
# cat: futures | currencies | commodities
FINAM_INSTRUMENTS = {
    # Фьючерсы (непрерывные тикеры Finam — без квартальных кодов экспирации)
    "IMOEXF@RTSX":  {"name": "IMOEXF / Индекс МосБиржи", "cat": "futures"},
    "RGBIF@RTSX":   {"name": "RGBIF / Индекс гособлигаций", "cat": "futures"},
    "SBERF@RTSX":   {"name": "SBERF / Фьючерс на Сбербанк", "cat": "futures"},
    "GAZPF@RTSX":   {"name": "GAZPF / Фьючерс на Газпром", "cat": "futures"},
    "SP500F@RTSX":  {"name": "SP500F / Индекс S&P 500", "cat": "futures"},
    "QQQF@RTSX":    {"name": "QQQF / Индекс Nasdaq-100", "cat": "futures"},
    "TSLAF@RTSX":   {"name": "TSLAF / Фьючерс на Tesla", "cat": "futures"},
    "AMZNF@RTSX":   {"name": "AMZNF / Фьючерс на Amazon", "cat": "futures"},
    "NFLXF@RTSX":   {"name": "NFLXF / Фьючерс на Netflix", "cat": "futures"},
    "COINF@RTSX":   {"name": "COINF / Фьючерс на Coinbase", "cat": "futures"},
    "UBERF@RTSX":   {"name": "UBERF / Фьючерс на Uber", "cat": "futures"},
    # Глобальные индексные/облигационные/крипто фьючерсы (непрерывные тикеры Finam,
    # биржи CME/CBOT/CBOE) — подтверждены живым запросом к /v1/instruments/{symbol}/bars
    "ES@XCME":   {"name": "ES / Индекс S&P 500 (CME)", "cat": "futures"},
    "NQ@XCME":   {"name": "NQ / Индекс Nasdaq-100 (CME)", "cat": "futures"},
    "YM@XCBT":   {"name": "YM / Индекс Dow Jones (CBOT)", "cat": "futures"},
    "RTY@XCME":  {"name": "RTY / Индекс Russell 2000 (CME)", "cat": "futures"},
    "NK@XCME":   {"name": "NK / Индекс Nikkei 225 (CME)", "cat": "futures"},
    "VX@XCBF":   {"name": "VX / Индекс волатильности VIX", "cat": "futures"},
    "ZN@XCBT":   {"name": "ZN / 10-летние гособлигации США", "cat": "futures"},
    "ZF@XCBT":   {"name": "ZF / 5-летние гособлигации США", "cat": "futures"},
    "BTC@XCME":  {"name": "BTC / Фьючерс на биткоин (CME)", "cat": "futures"},
    "ETH@XCME":  {"name": "ETH / Фьючерс на эфириум (CME)", "cat": "futures"},
    # Валюты (спот, борд MISX)
    "USD000UTSTOM@MISX": {"name": "USDRUB_TOM / Доллар-рубль", "cat": "currencies"},
    "EUR_RUB__TOM@MISX": {"name": "EURRUB_TOM / Евро-рубль", "cat": "currencies"},
    "CNYRUB_TOM@MISX":   {"name": "CNYRUB_TOM / Юань-рубль", "cat": "currencies"},
    "GBPRUB_TOM@MISX":   {"name": "GBPRUB_TOM / Фунт-рубль", "cat": "currencies"},
    "HKDRUB_TOM@MISX":   {"name": "HKDRUB_TOM / Гонконгский доллар-рубль", "cat": "currencies"},
    "TRYRUB_TOM@MISX":   {"name": "TRYRUB_TOM / Лира-рубль", "cat": "currencies"},
    "CHFRUB_TOM@MISX":   {"name": "CHFRUB_TOM / Франк-рубль", "cat": "currencies"},
    # Сырьё (спот в рублях, борд MISX)
    "GLDRUB_TOM@MISX": {"name": "GLDRUB_TOM / Золото", "cat": "commodities"},
    "SLVRUB_TOM@MISX": {"name": "SLVRUB_TOM / Серебро", "cat": "commodities"},
    # Мировые товарные фьючерсы (непрерывные тикеры Finam, биржи CME/NYMEX/COMEX/ICE/CBOT/LME) —
    # подтверждены живым запросом к /v1/instruments/{symbol}/bars
    "CL@XNYM":  {"name": "CL / Нефть WTI", "cat": "commodities"},
    "BZ@IFEU":  {"name": "BZ / Нефть Brent", "cat": "commodities"},
    "NG@XNYM":  {"name": "NG / Природный газ", "cat": "commodities"},
    "HO@XNYM":  {"name": "HO / Топочный мазут", "cat": "commodities"},
    "XRB@XNYM": {"name": "XRB / Бензин", "cat": "commodities"},
    "GC@XCEC":  {"name": "GC / Золото (COMEX)", "cat": "commodities"},
    "SI@XCEC":  {"name": "SI / Серебро (COMEX)", "cat": "commodities"},
    "HG@XCEC":  {"name": "HG / Медь", "cat": "commodities"},
    "PL@XNYM":  {"name": "PL / Платина", "cat": "commodities"},
    "PA@XNYM":  {"name": "PA / Палладий", "cat": "commodities"},
    "AH@XLME":  {"name": "AH / Алюминий (LME)", "cat": "commodities"},
    "NI@XLME":  {"name": "NI / Никель (LME)", "cat": "commodities"},
    "ZW@XCBT":  {"name": "ZW / Пшеница", "cat": "commodities"},
    "ZC@XCBT":  {"name": "ZC / Кукуруза", "cat": "commodities"},
    "ZS@XCBT":  {"name": "ZS / Соя", "cat": "commodities"},
    "KC@IFUS":  {"name": "KC / Кофе", "cat": "commodities"},
    "CC@IFUS":  {"name": "CC / Какао", "cat": "commodities"},
    "SB@IFUS":  {"name": "SB / Сахар", "cat": "commodities"},
    "CT@IFUS":  {"name": "CT / Хлопок", "cat": "commodities"},
    "OJ@IFUS":  {"name": "OJ / Апельсиновый сок", "cat": "commodities"},
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
