"""
Шифрование чужих секретов at-rest (API-ключи бирж пользователей).
Используется Fernet (симметричное шифрование) с ключом из CREDENTIALS_ENCRYPTION_KEY.
"""

from cryptography.fernet import Fernet, InvalidToken
from config import CREDENTIALS_ENCRYPTION_KEY

_fernet = Fernet(CREDENTIALS_ENCRYPTION_KEY.encode()) if CREDENTIALS_ENCRYPTION_KEY else None


def _require_fernet() -> Fernet:
    if _fernet is None:
        raise RuntimeError(
            "CREDENTIALS_ENCRYPTION_KEY не задан на сервере — хранение API-ключей недоступно"
        )
    return _fernet


def encrypt(value: str) -> str:
    """Шифрует строку, возвращает base64-токен для хранения в БД."""
    return _require_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Расшифровывает токен из БД обратно в исходную строку."""
    try:
        return _require_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Не удалось расшифровать сохранённый секрет — ключ шифрования изменился?")
