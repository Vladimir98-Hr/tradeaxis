"""
Модуль кеширования.
Предоставляет Redis-клиент и функции для работы с кешем.
"""

import asyncio
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


async def get_or_compute(key: str, compute, ttl: int = CACHE_TTL, lock_timeout: float = 20.0):
    """
    Защита от "cache stampede": если много запросов одновременно попадают на
    один и тот же остывший ключ (например, сотни пользователей смотрят одну
    и ту же бумагу сразу после истечения TTL), реальный расчёт (compute)
    выполнит только первый запрос — он берёт короткую распределённую блокировку
    в Redis. Остальные ждут и читают уже готовый результат из кеша, вместо
    того чтобы каждый долбил внешний API (Finam/биржу) отдельным запросом.

    Если Redis недоступен или держатель блокировки завис — не подвешиваем
    запрос навсегда, а считаем сами по истечении ожидания.
    """
    cached = await get_cached_data(key)
    if cached is not None:
        return cached

    lock_key = f"lock:{key}"
    got_lock = False
    try:
        got_lock = bool(await redis_client.set(lock_key, "1", nx=True, px=int(lock_timeout * 1000)))
    except redis_exceptions.RedisError:
        got_lock = True  # Redis недоступен — просто считаем сами, без координации

    if got_lock:
        try:
            result = await compute()
            await set_cached_data(key, result, ttl=ttl)
            return result
        finally:
            try:
                await redis_client.delete(lock_key)
            except redis_exceptions.RedisError:
                pass

    # Кто-то другой уже считает этот же ключ — ждём и подхватываем его результат
    deadline_steps = int(lock_timeout / 0.2)
    for _ in range(deadline_steps):
        await asyncio.sleep(0.2)
        cached = await get_cached_data(key)
        if cached is not None:
            return cached

    # Не дождались (держатель блокировки упал/завис) — считаем сами
    result = await compute()
    await set_cached_data(key, result, ttl=ttl)
    return result
