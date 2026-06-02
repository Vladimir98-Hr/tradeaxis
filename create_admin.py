"""
Скрипт для создания администратора.
Запускать один раз на сервере до открытия сайта:
    python create_admin.py
"""

import asyncio
import getpass
from sqlalchemy import select, func
from database import User, engine, async_session, init_db
from auth import hash_password


async def main():
    print("=== Создание администратора TradeAxis ===\n")

    username = input("Имя пользователя (логин): ").strip()
    if not username or len(username) < 3:
        print("Ошибка: минимум 3 символа")
        return

    email = input("Email: ").strip().lower()
    if not email or "@" not in email:
        print("Ошибка: введи корректный email")
        return

    password = getpass.getpass("Пароль (минимум 6 символов): ")
    if len(password) < 6:
        print("Ошибка: пароль минимум 6 символов")
        return

    confirm = getpass.getpass("Повтори пароль: ")
    if password != confirm:
        print("Ошибка: пароли не совпадают")
        return

    await init_db()

    async with async_session() as db:
        # Проверить что такого username нет
        res = await db.execute(select(User).where(User.username == username))
        if res.scalar_one_or_none():
            print(f"Ошибка: пользователь '{username}' уже существует")
            return

        res = await db.execute(select(User).where(User.email == email))
        if res.scalar_one_or_none():
            print(f"Ошибка: email '{email}' уже зарегистрирован")
            return

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_admin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    print(f"\n✓ Администратор '{username}' создан (ID={user.id})")
    print("Теперь можешь запускать сервер: python main.py")


if __name__ == "__main__":
    asyncio.run(main())
