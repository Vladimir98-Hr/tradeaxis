"""
Приватные (аутентифицированные) вызовы к биржам от имени пользователя —
для сверки результата дня (P&L reconciliation). В отличие от exchange.py
(один общий клиент на всё приложение, только публичные данные), здесь
клиент ccxt создаётся на каждый вызов с расшифрованными ключами конкретного
пользователя и никогда не кешируется/не шарится между пользователями.

Жёсткое архитектурное ограничение: этот модуль НИКОГДА не вызывает
createOrder/cancelOrder/withdraw или любые другие методы, изменяющие
состояние счёта — только чтение. Это гарантия на уровне кода, что даже
ключ с более широкими правами, чем нужно, не может быть использован этим
приложением для торговли или вывода средств.
"""

import asyncio
import ccxt
from datetime import datetime, timezone

# Биржи, поддержанные для приватных вызовов, и их обязательные поля credential'ов.
SUPPORTED_EXCHANGES = {
    "okx": ["apiKey", "secret", "password"],   # password = passphrase OKX
    "bybit": ["apiKey", "secret"],
}


def _require_supported(exchange_id: str):
    if exchange_id not in SUPPORTED_EXCHANGES:
        raise ValueError(f"Биржа '{exchange_id}' не поддерживается для синхронизации счёта")


def _build_client(exchange_id: str, api_key: str, api_secret: str, api_passphrase: str | None):
    """Создаёт одноразовый ccxt-клиент с ключами пользователя. Не кешируется."""
    _require_supported(exchange_id)
    params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
    if api_passphrase:
        params["password"] = api_passphrase
    client = getattr(ccxt, exchange_id)(params)
    return client


async def verify_credentials(exchange_id: str, api_key: str, api_secret: str, api_passphrase: str | None = None) -> None:
    """
    Тестовый read-only вызов для проверки ключа перед сохранением в БД.
    Бросает исключение с понятным сообщением, если ключ невалиден/недостаточно прав.
    """
    client = _build_client(exchange_id, api_key, api_secret, api_passphrase)
    try:
        await asyncio.to_thread(client.fetch_balance)
    except ccxt.AuthenticationError as e:
        raise ValueError("Биржа отклонила ключ (неверный key/secret/passphrase)") from e
    except ccxt.PermissionDenied as e:
        raise ValueError("У ключа недостаточно прав на чтение баланса") from e
    except ccxt.BaseError as e:
        raise ValueError(f"Не удалось проверить ключ: {e}") from e
    finally:
        try:
            await asyncio.to_thread(client.close)
        except Exception:
            pass


async def fetch_daily_summary(
    exchange_id: str,
    api_key: str,
    api_secret: str,
    api_passphrase: str | None,
    date: str,
) -> dict:
    """
    Считает сводку за календарный день (UTC) `date` (YYYY-MM-DD):
    реализованные сделки, комиссии, funding, переводы.
    Только чтение (fetchMyTrades/fetchFundingHistory/fetchLedger) — никаких
    вызовов, изменяющих состояние счёта.
    """
    client = _build_client(exchange_id, api_key, api_secret, api_passphrase)
    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999000)
    since_ms = int(day_start.timestamp() * 1000)
    until_ms = int(day_end.timestamp() * 1000)

    trades, funding, ledger = [], [], []
    errors = []
    capital = None

    try:
        balance = await asyncio.to_thread(client.fetch_balance)
        # Берём суммарный капитал в стейблкоине счёта (USDT — основная расчётная
        # валюта на спот/фьючерсных счетах поддерживаемых бирж). Это приближение:
        # если на счету есть и другие активы, их стоимость здесь не учтена —
        # для калькулятора риска важен именно доступный торговый капитал, а не
        # весь портфель, поэтому такое упрощение осознанно, не случайный баг.
        total = balance.get("total") or {}
        capital = float(total.get("USDT") or total.get("USD") or 0) or None
    except ccxt.BaseError as e:
        errors.append(f"баланс: {e}")

    try:
        if client.has.get("fetchMyTrades"):
            raw = await asyncio.to_thread(client.fetch_my_trades, None, since_ms, 200)
            trades = [t for t in raw if since_ms <= t["timestamp"] <= until_ms]
    except ccxt.BaseError as e:
        errors.append(f"сделки: {e}")

    try:
        if client.has.get("fetchFundingHistory"):
            raw = await asyncio.to_thread(client.fetch_funding_history, None, since_ms, 200)
            funding = [f for f in raw if since_ms <= f["timestamp"] <= until_ms]
    except ccxt.BaseError as e:
        errors.append(f"funding: {e}")

    try:
        if client.has.get("fetchLedger"):
            raw = await asyncio.to_thread(client.fetch_ledger, None, since_ms, 200)
            ledger = [l for l in raw if since_ms <= (l.get("timestamp") or 0) <= until_ms]
    except ccxt.BaseError as e:
        errors.append(f"переводы/баланс: {e}")

    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass

    # Приближённый реализованный P&L: сумма (продажи - покупки) по сделкам дня.
    # Это не полный FIFO/LIFO-расчёт прибыли по позициям (для него нужна история
    # до начала дня) — для деривативов/маржинальных позицийточнее использовать
    # funding+комиссии как есть, а сам P&L сверять с `realizedPnl` биржи, если
    # ccxt его отдаёт в структуре сделки/позиции (расширить при необходимости).
    realized_pnl = sum(float(t.get("cost") or 0) * (1 if t.get("side") == "sell" else -1) for t in trades)
    fees = sum(float((t.get("fee") or {}).get("cost") or 0) for t in trades)
    funding_total = sum(float(f.get("amount") or 0) for f in funding)
    transfers = [
        l for l in ledger
        if l.get("type") in ("transfer", "deposit", "withdrawal")
    ]
    transfers_total = sum(float(t.get("amount") or 0) for t in transfers)

    return {
        "date": date,
        "exchange_id": exchange_id,
        "capital": round(capital, 2) if capital is not None else None,
        "trades_count": len(trades),
        "realized_pnl": round(realized_pnl, 8),
        "fees": round(fees, 8),
        "funding": round(funding_total, 8),
        "transfers": round(transfers_total, 8),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "partial": bool(errors),
        "errors": errors,
    }
