"""Run from project root: python -m backend.manage create-user."""
import argparse
import getpass

from sqlalchemy import select

from .database import User, initialize, make_database
from .main import PASSWORDS, normalize_email
from .services import now_iso


def main():
    parser = argparse.ArgumentParser(description="Управление Сводом")
    parser.add_argument("command", choices=["init-db", "create-user"])
    args = parser.parse_args()
    engine, sessions = make_database()
    initialize(engine)
    if args.command == "init-db":
        print("Схема базы данных готова (версия 3).")
        return
    email = normalize_email(input("Почта нового пользователя: "))
    name = input("Имя: ").strip()
    password = getpass.getpass("Пароль (минимум 6 символов): ")
    repeat = getpass.getpass("Повторите пароль: ")
    if not 1 <= len(name) <= 80 or not 6 <= len(password) <= 128 or password != repeat:
        raise SystemExit("Проверьте имя и пароль. Профиль не создан.")
    with sessions() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("Такой профиль уже существует.")
        db.add(User(email=email, name=name, password_hash=PASSWORDS.hash(password), created_at=now_iso()))
        db.commit()
    print("Профиль создан. Можно войти в приложение.")


if __name__ == "__main__":
    main()
