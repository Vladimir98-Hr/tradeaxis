"""
Модуль кеширования.
Предоставляет Redis-клиент и функции для работы с кешем.
"""

import redis.asyncio as redis
import json
import hashlib
from config import REDIS_URL, CACHE_TTL

# Асинхронный клиент Redis
redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


def get_cache_key(symbol: str, timeframe: str, limit: int, endpoint: str) -> str:
    """Генерирует уникальный ключ кеша на основе параметров запроса."""
    key_string = f"{endpoint}:{symbol}:{timeframe}:{limit}"
    return hashlib.md5(key_string.encode()).hexdigest()


async def get_cached_data(key: str):
    """Получает данные из кеша по ключу. Возвращает None, если данных нет."""
    data = await redis_client.get(key)
    if data:
        return json.loads(data)
    return None


async def set_cached_data(key: str, data: dict, ttl: int = CACHE_TTL):
    """Сохраняет данные в кеш с указанным временем жизни (TTL)."""
    await redis_client.setex(key, ttl, json.dumps(data))
