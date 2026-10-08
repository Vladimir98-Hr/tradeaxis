"""
Модуль для получения данных через Finam Trade API.
Требует secret-токен из личного кабинета Финама (FINAM_SECRET_TOKEN в .env).
Документация: https://api.finam.ru/docs/rest/
"""

import asyncio
import itertools
import re
import httpx
import pandas as pd
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from config import FINAM_SECRET_TOKENS

FINAM_BASE_URL = "https://api.finam.ru"

# Таймфреймы: наш формат → формат Finam Trade API
FINAM_TIMEFRAMES = {
    '1m': 'TIME_FRAME_M1',
    '5m': 'TIME_FRAME_M5',
    '15m': 'TIME_FRAME_M15',
    '1h': 'TIME_FRAME_H1',
    '4h': 'TIME_FRAME_H4',
    '1d': 'TIME_FRAME_D',
    '1w': 'TIME_FRAME_W',
}

_INTERVAL_DELTA = {
    '1m': timedelta(minutes=1),
    '5m': timedelta(minutes=5),
    '15m': timedelta(minutes=15),
    '1h': timedelta(hours=1),
    '4h': timedelta(hours=4),
    '1d': timedelta(days=1),
    '1w': timedelta(weeks=1),
}

# Finam Trade API отклоняет запрос свечей 400 Bad Request, если диапазон
# interval.start_time..interval.end_time превышает лимит, зависящий от таймфрейма
# (подтверждено эмпирически: H1/H4 — около 31 дня, D — около 365 дней).
# Ограничиваем диапазон снизу, чтобы не упереться в этот лимит при большом
# chartLimit на фронтенде — вместо ошибки просто вернём меньше баров, чем limit.
_MAX_RANGE_DAYS = {
    '1m': 30, '5m': 30, '15m': 30,
    '1h': 30, '4h': 30,
    '1d': 360,
    '1w': 1275,
}

# Целевая глубина истории (в днях) для каждого таймфрейма — тянем её постранично
# окнами по _MAX_RANGE_DAYS (несколько запросов параллельно), т.к. за один запрос
# Finam отдаёт максимум ~_MAX_RANGE_DAYS. 1m сюда не входит — для тиковых минутных
# свечей глубокая история не нужна, там действует обычная логика по limit.
_HISTORY_DAYS = {
    '5m': 30, '15m': 30,     # ~1 месяц
    '1h': 150, '4h': 150,    # ~5 месяцев
    '1d': 3650, '1w': 3650,  # ~10 лет
}

# Список инструментов меняется редко — кешируем на несколько часов
_assets_cache: dict = {"data": None, "expires_at": None}


class _RateLimiter:
    """
    Троттлинг запросов к Finam API — не "сколько одновременно", а "сколько в
    секунду". Раньше лимитер был один общий на всё приложение; теперь у
    каждого _FinamAccount (см. ниже) свой собственный лимитер, т.к. лимит
    Finam документирован как 200 запросов/мин на уровне API-доступа — в
    отсутствие информации об обратном считаем его привязанным к токену, и
    каждый токен получает свой независимый бюджет. Семафоры на конкурентность
    (asyncio.Semaphore в сканерах) ограничивают только число ОДНОВРЕМЕННЫХ
    запросов, но не защищают от превышения лимита, если разные задачи шлют
    запросы по очереди быстрее, чем Finam готов их принимать — именно так
    сервис упал в понедельник утром: несколько независимых фоновых циклов +
    реальные пользователи в сумме превысили лимит, хотя каждый по отдельности
    был в рамках своих локальных ограничений.
    """
    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self):
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            delay = self._next_allowed - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = loop.time()
            self._next_allowed = now + self._min_interval


class _FinamAccount:
    """
    Один secret-токен Finam со своим JWT-кешем и своим rate-limiter'ом.
    Несколько аккаунтов (см. _accounts) дают независимые бюджеты запросов —
    суммарная пропускная способность приложения растёт пропорционально
    числу токенов вместо одного общего потолка на всех.
    """
    def __init__(self, token: str):
        self.token = token
        self.jwt: str | None = None
        self.jwt_expires_at: datetime | None = None
        # Официальный лимит Finam — 200 запросов/мин (~3.3/сек), но это средняя
        # скорость, а не защита от коротких залпов: несколько независимых
        # источников (фоновые сканеры + живые графики пользователей) могут
        # одновременно выбрать разные токены и выстрелить залпом — поэтому
        # берём на токен тот же проверенный безопасный темп, что раньше был
        # общим на всё приложение (2 запроса/сек), а не ближе к официальному
        # пределу — рост пропускной способности даёт само умножение на число
        # токенов, а не агрессивность каждого из них.
        self.rate_limiter = _RateLimiter(min_interval=0.5)


_accounts: list[_FinamAccount] = [_FinamAccount(t) for t in FINAM_SECRET_TOKENS]
_account_cycle = itertools.cycle(_accounts) if _accounts else None


def _require_token():
    if not _accounts:
        raise HTTPException(
            status_code=400,
            detail="Finam Trade API не настроен: отсутствует FINAM_SECRET_TOKEN(S) на сервере",
        )


async def _get_jwt_token_for(account: _FinamAccount) -> str:
    """
    Возвращает действующий JWT-токен аккаунта, обновляя его при необходимости.
    Finam выдаёт JWT на 15 минут по secret-токену через POST /v1/sessions.
    """
    now = datetime.now(timezone.utc)
    if account.jwt and account.jwt_expires_at and now < account.jwt_expires_at:
        return account.jwt

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{FINAM_BASE_URL}/v1/sessions",
                json={"secret": account.token},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Finam Trade API недоступен: {e}")

    if resp.status_code == 401 or resp.status_code == 403:
        raise HTTPException(
            status_code=502,
            detail="Finam Trade API отклонил secret-токен (401/403) — проверьте FINAM_SECRET_TOKEN(S)",
        )
    resp.raise_for_status()

    data = resp.json()
    token = data.get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Finam Trade API не вернул JWT-токен")

    account.jwt = token
    # Запас в 1 минуту до истечения реального 15-минутного срока действия
    account.jwt_expires_at = now + timedelta(minutes=14)
    return token


async def get_jwt_token() -> str:
    """Обратная совместимость: JWT первого аккаунта из пула."""
    _require_token()
    return await _get_jwt_token_for(_accounts[0])


async def _finam_get(
    path: str,
    params: dict | None = None,
    retries: int = 2,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """
    client — переиспользуемое HTTP-соединение для серии запросов подряд
    (пагинация), чтобы не тратить время на TLS-хендшейк на каждый вызов.
    Без него открывается разовое соединение, как раньше.

    Каждый вызов выбирает следующий аккаунт из пула по кругу (round-robin) —
    распределяет нагрузку по всем доступным токенам вне зависимости от того,
    как запросы сгруппированы по инструментам/окнам пагинации выше по стеку.

    429 обрабатывается отдельным retry-с-backoff прямо здесь: при загрузке
    глубокой истории уходит до ~11 параллельных запросов на один график, и
    без этого один-единственный 429 среди них ронял всю загрузку целиком —
    именно так возникала картина "шапка уже Сбер, а график всё ещё биткоин".
    """
    _require_token()
    account = next(_account_cycle)
    token = await _get_jwt_token_for(account)

    async def _request(c: httpx.AsyncClient):
        for attempt in range(retries + 1):
            await account.rate_limiter.wait()
            try:
                resp = await c.get(
                    f"{FINAM_BASE_URL}{path}",
                    params=params or {},
                    headers={"Authorization": token},
                )
            except httpx.HTTPError as e:
                if attempt >= retries:
                    raise HTTPException(status_code=502, detail=f"Finam Trade API недоступен: {e}")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if resp.status_code == 429 and attempt < retries:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.replace('.', '', 1).isdigit() else 1.5 * (attempt + 1)
                await asyncio.sleep(delay)
                continue

            return resp

    if client is not None:
        resp = await _request(client)
    else:
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await _request(c)

    if resp.status_code in (401, 403):
        # Токен мог протухнуть раньше срока — сбрасываем кеш именно этого аккаунта
        account.jwt = None
        raise HTTPException(status_code=502, detail="Finam Trade API отклонил запрос (401/403)")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Finam Trade API: превышен лимит запросов, попробуйте через несколько секунд")
    resp.raise_for_status()
    return resp.json()


async def fetch_ohlcv_finam(symbol: str, timeframe: str = '1d', limit: int = 100, deep_history: bool = True) -> pd.DataFrame:
    """
    Загружает OHLCV-свечи через Finam Trade API.
    symbol в формате TICKER@MIC, например SBER@MISX.
    Возвращает DataFrame с колонками: timestamp, Open, High, Low, Close, Volume —
    тем же форматом, что и moex.fetch_ohlcv_moex(), чтобы indicators.py работал без изменений.

    deep_history=False отключает постраничную загрузку глубокой истории (см. _HISTORY_DAYS)
    и всегда тянет один запрос на ~limit последних баров — для сканеров, которым нужен
    только короткий хвост по многим инструментам сразу, а не вся история по одному.
    """
    tf = FINAM_TIMEFRAMES.get(timeframe, 'TIME_FRAME_D')
    delta = _INTERVAL_DELTA.get(timeframe, timedelta(days=1))
    max_range_days = _MAX_RANGE_DAYS.get(timeframe, 360)
    end_time = datetime.now(timezone.utc)
    history_days = _HISTORY_DAYS.get(timeframe) if deep_history else None

    if history_days:
        # Глубокая история: разбиваем весь диапазон на окна по max_range_days
        # (лимит Finam на один запрос) и тянем их параллельно — иначе глубокая
        # история собирается пачкой последовательных запросов и грузится
        # заметно дольше, чем нужно для интерактивного открытия графика.
        earliest_allowed = end_time - timedelta(days=history_days)
        windows = []
        window_end = end_time
        while window_end > earliest_allowed:
            window_start = max(window_end - timedelta(days=max_range_days), earliest_allowed)
            windows.append((window_start, window_end))
            window_end = window_start

        # Прогреваем JWT всех аккаунтов пула один раз до параллельных запросов —
        # иначе первые несколько окон на каждый аккаунт долбят /v1/sessions разом.
        await asyncio.gather(*[_get_jwt_token_for(a) for a in _accounts])
        # Полностью безлимитный параллелизм (по числу окон, до ~11) давал лишнюю
        # нагрузку по памяти/сокетам на тесном VPS (1.8GB) — фиксированный потолок
        # всё ещё покрывает большинство окон одним залпом. Растёт с числом
        # аккаунтов, но умеренно: слишком большой залп одновременных запросов
        # (даже распределённых по разным токенам) всё равно может натолкнуться
        # на чувствительность Finam к коротким всплескам, а не только к
        # среднему темпу — см. комментарий у _scan_sem в finam_routes.py.
        sem = asyncio.Semaphore(min(4 * len(_accounts), 10))

        async def _fetch_window(ws: datetime, we: datetime, client: httpx.AsyncClient):
            async with sem:
                data = await _finam_get(
                    f"/v1/instruments/{symbol}/bars",
                    params={
                        "timeframe": tf,
                        "interval.start_time": ws.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        "interval.end_time": we.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    },
                    retries=3,
                    client=client,
                )
                return data.get("bars", [])

        async with httpx.AsyncClient(timeout=20) as shared_client:
            pages = await asyncio.gather(*[_fetch_window(ws, we, shared_client) for ws, we in windows])

        bars = []
        for page in reversed(pages):  # windows идут от новых к старым — собираем в хронологическом порядке
            bars.extend(page)

        # Дедуп на случай, если соседние окна вернули одну и ту же граничную свечу
        seen = set()
        deduped = []
        for b in bars:
            ts = b.get("timestamp")
            if ts in seen:
                continue
            seen.add(ts)
            deduped.append(b)
        bars = deduped
    else:
        desired_start = end_time - delta * (limit + 5)
        earliest_start = end_time - timedelta(days=max_range_days)
        start_time = max(desired_start, earliest_start)

        data = await _finam_get(
            f"/v1/instruments/{symbol}/bars",
            params={
                "timeframe": tf,
                "interval.start_time": start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                "interval.end_time": end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            },
        )
        bars = data.get("bars", [])

    if not bars:
        raise ValueError(f"Finam Trade API: нет данных для {symbol} ({timeframe})")

    def _num(field):
        """Finam оборачивает числа в {"value": "123.45"} (protobuf Decimal)."""
        if isinstance(field, dict):
            return float(field.get('value', 0) or 0)
        return float(field or 0)

    result = pd.DataFrame({
        'timestamp': [pd.to_datetime(b['timestamp']).strftime('%Y-%m-%d %H:%M:%S') for b in bars],
        'Open': [_num(b['open']) for b in bars],
        'High': [_num(b['high']) for b in bars],
        'Low': [_num(b['low']) for b in bars],
        'Close': [_num(b['close']) for b in bars],
        'Volume': [_num(b.get('volume', 0)) for b in bars],
    })

    # Для таймфреймов с глубокой историей отдаём всё, что накопили постранично —
    # limit там относится только к «баров за один запрос» на 1m (без пагинации).
    if history_days:
        return result.reset_index(drop=True)
    return result.tail(limit).reset_index(drop=True)


# Биржевые коды (mic), интересные для раздела Finam:
# MISX/RTSX — Мосбиржа (акции, валюты, рублёвые фьючерсы),
# остальные — мировые товарные/индексные биржи (CME, NYMEX, COMEX, ICE, CBOT, LME),
# на которых Finam также даёт торговать (нефть, металлы, зерно, индексы и т.д.)
_RELEVANT_MICS = {"MISX", "RTSX", "XLME", "XNYM", "XCEC", "IFEU", "IFUS", "XCBT", "XCBF", "XCME"}

# Тикер конкретного экспирирующегося контракта (например SiU6, NGV26) оканчивается
# на код месяца + год — такие тикеры не нужны в списке инструментов, нужен только
# непрерывный тикер без даты (например GAZPF, CL, GC).
_DATED_FUTURE_RE = re.compile(r"[FGHJKMNQUVXZ]\d{1,2}$")


def _is_continuous_ticker(ticker: str) -> bool:
    return not _DATED_FUTURE_RE.search(ticker or "")


async def _refresh_finam_assets_cache() -> None:
    """
    Полный обход каталога Finam (/v1/assets/all, постранично) в фоне —
    вызывается из background-задачи при старте приложения и раз в несколько часов,
    НЕ из обработчика запроса (каталог Finam содержит 100k+ инструментов по всем
    мировым биржам, полный обход занимает минуты). Пока кеш не прогрет, роуты
    Finam отдают только надёжный curated-список из config.py.
    """
    assets = []
    cursor = None
    for _ in range(400):  # с запасом — полный обход каталога по всем страницам
        params = {"only_active": "true"}
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _finam_get("/v1/assets/all", params=params)
        except HTTPException:
            break
        page = data.get("assets", [])
        if not page:
            break
        for a in page:
            if a.get("mic") not in _RELEVANT_MICS:
                continue
            if a.get("type") == "FUTURES" and not _is_continuous_ticker(a.get("ticker", "")):
                continue
            assets.append(a)
        cursor = data.get("cursor") or data.get("next_cursor")
        if not cursor:
            break
        await asyncio.sleep(0.15)

    if assets:
        _assets_cache["data"] = assets
        _assets_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(hours=6)


async def run_finam_catalog_refresher() -> None:
    """Фоновый цикл: обновляет кеш каталога Finam при старте и затем каждые 6 часов."""
    if not _accounts:
        return
    while True:
        try:
            await _refresh_finam_assets_cache()
        except Exception:
            pass
        await asyncio.sleep(6 * 3600)


async def fetch_finam_assets() -> list:
    """
    Возвращает закешированный список инструментов Finam (акции/фьючерсы/сырьё/валюты),
    собранный фоновой задачей run_finam_catalog_refresher(). Не делает сетевых
    запросов сама — если фоновый обход ещё не завершился (первые минуты после
    старта сервера), возвращает пустой список, и роуты используют только
    curated-список из config.py.
    """
    return _assets_cache["data"] or []


async def fetch_finam_quote(symbol: str) -> dict:
    """Возвращает последнюю котировку по инструменту (TICKER@MIC)."""
    data = await _finam_get(f"/v1/instruments/{symbol}/quotes/latest")
    return data.get("quote", {})
