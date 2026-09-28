"""
Модуль кеширования.
Предоставляет Redis-клиент и функции для работы с кешем.
"""

import redis.asyncio as redis
from redis import exceptions as redis_exceptions
import json
import hashlib
import logging
from config import REDIS_URL, CACHE_TTL

logger = logging.getLogger(__name__)

# Асинхронный клиент Redis
redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


def get_cache_key(symbol: str, timeframe: str, limit: int, endpoint: str) -> str:
    """Генерирует уникальный ключ кеша на основе параметров запроса."""
    key_string = f"{endpoint}:{symbol}:{timeframe}:{limit}"
    return hashlib.md5(key_string.encode()).hexdigest()


async def get_cached_data(key: str):
    """
    Получает данные из кеша по ключу. Возвращает None, если данных нет —
    в том числе если Redis временно недоступен/подвис: кеш не должен ронять
    запрос целиком, эндпоинт просто сходит за свежими данными сам.
    """
    try:
        data = await redis_client.get(key)
    except redis_exceptions.RedisError:
        logger.warning("Redis недоступен при чтении кеша, пропускаем", exc_info=True)
        return None
    if data:
        return json.loads(data)
    return None


async def set_cached_data(key: str, data: dict, ttl: int = CACHE_TTL):
    """Сохраняет данные в кеш с указанным TTL. Ошибка Redis не должна ронять запрос."""
    try:
        await redis_client.setex(key, ttl, json.dumps(data))
    except redis_exceptions.RedisError:
        logger.warning("Redis недоступен при записи кеша, пропускаем", exc_info=True)
