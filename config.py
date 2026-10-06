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

# Finam Trade API — secret-токен(ы) из личного кабинета Финама, раздел «Токены».
# Пусто = раздел Finam в терминале недоступен. Доступен всем зарегистрированным пользователям.
#
# Можно указать несколько токенов (с разных счётов/кабинетов) через запятую в
# FINAM_SECRET_TOKENS — тогда запросы сканеров распределяются между ними по
# кругу (round-robin), и суммарный лимит запросов к Finam растёт пропорционально
# числу токенов (см. finam.py: _FinamAccount, _accounts). FINAM_SECRET_TOKEN
# оставлен для обратной совместимости — используется как единственный токен,
# если FINAM_SECRET_TOKENS не задан.
_finam_tokens_raw = os.getenv("FINAM_SECRET_TOKENS", "")
if _finam_tokens_raw.strip():
    FINAM_SECRET_TOKENS = [t.strip() for t in _finam_tokens_raw.split(",") if t.strip()]
else:
    FINAM_SECRET_TOKEN = os.getenv("FINAM_SECRET_TOKEN", "")
    FINAM_SECRET_TOKENS = [FINAM_SECRET_TOKEN] if FINAM_SECRET_TOKEN else []
FINAM_SECRET_TOKEN = FINAM_SECRET_TOKENS[0] if FINAM_SECRET_TOKENS else ""

# Акции Finam (те же эмитенты MOEX, но тикеры в формате TICKER@MISX для Finam Trade API)
# Все акции MOEX торгуются в рублях напрямую (цена = рубли за акцию) — спот,
# без пунктов/контрактной стоимости, поэтому point_based всегда False.
FINAM_SYMBOLS = {
    "SBER":  {"name": "SBER / Сбербанк",      "base": "SBER",  "currency": "RUB", "point_based": False},
    "GAZP":  {"name": "GAZP / Газпром",        "base": "GAZP",  "currency": "RUB", "point_based": False},
    "LKOH":  {"name": "LKOH / Лукойл",        "base": "LKOH",  "currency": "RUB", "point_based": False},
    "YDEX":  {"name": "YDEX / Яндекс",        "base": "YDEX",  "currency": "RUB", "point_based": False},
    "NVTK":  {"name": "NVTK / Новатэк",       "base": "NVTK",  "currency": "RUB", "point_based": False},
    "ROSN":  {"name": "ROSN / Роснефть",      "base": "ROSN",  "currency": "RUB", "point_based": False},
    "GMKN":  {"name": "GMKN / Норникель",     "base": "GMKN",  "currency": "RUB", "point_based": False},
    "MTSS":  {"name": "MTSS / МТС",           "base": "MTSS",  "currency": "RUB", "point_based": False},
    "SBERP": {"name": "SBERP / Сбербанк п",   "base": "SBERP", "currency": "RUB", "point_based": False},
    "VTBR":  {"name": "VTBR / ВТБ",           "base": "VTBR",  "currency": "RUB", "point_based": False},
    "MGNT":  {"name": "MGNT / Магнит",        "base": "MGNT",  "currency": "RUB", "point_based": False},
    "TATN":  {"name": "TATN / Татнефть",      "base": "TATN",  "currency": "RUB", "point_based": False},
    "ALRS":  {"name": "ALRS / Алроса",        "base": "ALRS",  "currency": "RUB", "point_based": False},
    "PLZL":  {"name": "PLZL / Полюс",         "base": "PLZL",  "currency": "RUB", "point_based": False},
    "MOEX":  {"name": "MOEX / Московская биржа", "base": "MOEX", "currency": "RUB", "point_based": False},
}

# Фьючерсы, валюты и сырьё Finam. symbol — точный тикер в формате Finam (TICKER@MIC),
# подтверждён живым запросом к /v1/assets/all и /v1/instruments/{symbol}/bars.
# cat: futures | currencies | commodities
#
# currency/point_based — для калькулятора риска:
# - point_based=False: цена инструмента — это сразу деньги за единицу (как акция),
#   currency фиксирована (RUB для всех валютных/рублёвых спот-пар).
# - point_based=True: цена инструмента — пункты, не деньги; перевод пункта в деньги
#   (стоимость шага цены) зависит от спецификации конкретного контракта и у нас НЕТ
#   надёжных данных по ней из Finam API — currency оставлена None, пользователь вводит
#   стоимость пункта и её валюту вручную в калькуляторе риска (без авто-подсказок).
FINAM_INSTRUMENTS = {
    # Фьючерсы (непрерывные тикеры Finam — без квартальных кодов экспирации)
    "IMOEXF@RTSX":  {"name": "IMOEXF / Индекс МосБиржи", "cat": "futures", "currency": None, "point_based": True},
    "RGBIF@RTSX":   {"name": "RGBIF / Индекс гособлигаций", "cat": "futures", "currency": None, "point_based": True},
    "SBERF@RTSX":   {"name": "SBERF / Фьючерс на Сбербанк", "cat": "futures", "currency": None, "point_based": True},
    "GAZPF@RTSX":   {"name": "GAZPF / Фьючерс на Газпром", "cat": "futures", "currency": None, "point_based": True},
    "SP500F@RTSX":  {"name": "SP500F / Индекс S&P 500", "cat": "futures", "currency": None, "point_based": True},
    "QQQF@RTSX":    {"name": "QQQF / Индекс Nasdaq-100", "cat": "futures", "currency": None, "point_based": True},
    "TSLAF@RTSX":   {"name": "TSLAF / Фьючерс на Tesla", "cat": "futures", "currency": None, "point_based": True},
    "AMZNF@RTSX":   {"name": "AMZNF / Фьючерс на Amazon", "cat": "futures", "currency": None, "point_based": True},
    "NFLXF@RTSX":   {"name": "NFLXF / Фьючерс на Netflix", "cat": "futures", "currency": None, "point_based": True},
    "COINF@RTSX":   {"name": "COINF / Фьючерс на Coinbase", "cat": "futures", "currency": None, "point_based": True},
    "UBERF@RTSX":   {"name": "UBERF / Фьючерс на Uber", "cat": "futures", "currency": None, "point_based": True},
    # Глобальные индексные/облигационные/крипто фьючерсы (непрерывные тикеры Finam,
    # биржи CME/CBOT/CBOE) — подтверждены живым запросом к /v1/instruments/{symbol}/bars
    "ES@XCME":   {"name": "ES / Индекс S&P 500 (CME)", "cat": "futures", "currency": None, "point_based": True},
    "NQ@XCME":   {"name": "NQ / Индекс Nasdaq-100 (CME)", "cat": "futures", "currency": None, "point_based": True},
    "YM@XCBT":   {"name": "YM / Индекс Dow Jones (CBOT)", "cat": "futures", "currency": None, "point_based": True},
    "RTY@XCME":  {"name": "RTY / Индекс Russell 2000 (CME)", "cat": "futures", "currency": None, "point_based": True},
    "NK@XCME":   {"name": "NK / Индекс Nikkei 225 (CME)", "cat": "futures", "currency": None, "point_based": True},
    "VX@XCBF":   {"name": "VX / Индекс волатильности VIX", "cat": "futures", "currency": None, "point_based": True},
    "ZN@XCBT":   {"name": "ZN / 10-летние гособлигации США", "cat": "futures", "currency": None, "point_based": True},
    "ZF@XCBT":   {"name": "ZF / 5-летние гособлигации США", "cat": "futures", "currency": None, "point_based": True},
    "BTC@XCME":  {"name": "BTC / Фьючерс на биткоин (CME)", "cat": "futures", "currency": None, "point_based": True},
    "ETH@XCME":  {"name": "ETH / Фьючерс на эфириум (CME)", "cat": "futures", "currency": None, "point_based": True},
    # Валюты (спот, борд MISX) — цена сразу в рублях за единицу базовой валюты
    "USD000UTSTOM@MISX": {"name": "USDRUB_TOM / Доллар-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "EUR_RUB__TOM@MISX": {"name": "EURRUB_TOM / Евро-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "CNYRUB_TOM@MISX":   {"name": "CNYRUB_TOM / Юань-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "GBPRUB_TOM@MISX":   {"name": "GBPRUB_TOM / Фунт-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "HKDRUB_TOM@MISX":   {"name": "HKDRUB_TOM / Гонконгский доллар-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "TRYRUB_TOM@MISX":   {"name": "TRYRUB_TOM / Лира-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    "CHFRUB_TOM@MISX":   {"name": "CHFRUB_TOM / Франк-рубль", "cat": "currencies", "currency": "RUB", "point_based": False},
    # Сырьё (спот в рублях, борд MISX) — цена сразу в рублях за единицу товара
    "GLDRUB_TOM@MISX": {"name": "GLDRUB_TOM / Золото", "cat": "commodities", "currency": "RUB", "point_based": False},
    "SLVRUB_TOM@MISX": {"name": "SLVRUB_TOM / Серебро", "cat": "commodities", "currency": "RUB", "point_based": False},
    # Мировые товарные фьючерсы (непрерывные тикеры Finam, биржи CME/NYMEX/COMEX/ICE/CBOT/LME) —
    # подтверждены живым запросом к /v1/instruments/{symbol}/bars; цена в пунктах, не в деньгах
    "CL@XNYM":  {"name": "CL / Нефть WTI", "cat": "commodities", "currency": None, "point_based": True},
    "BZ@IFEU":  {"name": "BZ / Нефть Brent", "cat": "commodities", "currency": None, "point_based": True},
    "NG@XNYM":  {"name": "NG / Природный газ", "cat": "commodities", "currency": None, "point_based": True},
    "HO@XNYM":  {"name": "HO / Топочный мазут", "cat": "commodities", "currency": None, "point_based": True},
    "XRB@XNYM": {"name": "XRB / Бензин", "cat": "commodities", "currency": None, "point_based": True},
    "GC@XCEC":  {"name": "GC / Золото (COMEX)", "cat": "commodities", "currency": None, "point_based": True},
    "SI@XCEC":  {"name": "SI / Серебро (COMEX)", "cat": "commodities", "currency": None, "point_based": True},
    "HG@XCEC":  {"name": "HG / Медь", "cat": "commodities", "currency": None, "point_based": True},
    "PL@XNYM":  {"name": "PL / Платина", "cat": "commodities", "currency": None, "point_based": True},
    "PA@XNYM":  {"name": "PA / Палладий", "cat": "commodities", "currency": None, "point_based": True},
    "AH@XLME":  {"name": "AH / Алюминий (LME)", "cat": "commodities", "currency": None, "point_based": True},
    "NI@XLME":  {"name": "NI / Никель (LME)", "cat": "commodities", "currency": None, "point_based": True},
    "ZW@XCBT":  {"name": "ZW / Пшеница", "cat": "commodities", "currency": None, "point_based": True},
    "ZC@XCBT":  {"name": "ZC / Кукуруза", "cat": "commodities", "currency": None, "point_based": True},
    "ZS@XCBT":  {"name": "ZS / Соя", "cat": "commodities", "currency": None, "point_based": True},
    "KC@IFUS":  {"name": "KC / Кофе", "cat": "commodities", "currency": None, "point_based": True},
    "CC@IFUS":  {"name": "CC / Какао", "cat": "commodities", "currency": None, "point_based": True},
    "SB@IFUS":  {"name": "SB / Сахар", "cat": "commodities", "currency": None, "point_based": True},
    "CT@IFUS":  {"name": "CT / Хлопок", "cat": "commodities", "currency": None, "point_based": True},
    "OJ@IFUS":  {"name": "OJ / Апельсиновый сок", "cat": "commodities", "currency": None, "point_based": True},
}
