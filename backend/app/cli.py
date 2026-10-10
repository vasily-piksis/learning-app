import argparse
import getpass
import re
from sqlalchemy import select, delete
from .auth import hasher
from .models import User, AuthSession
from .config import Settings
from .db import Database


def create_user(db, username, display_name, password):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{1,80}", username) or len(password) < 10:
        raise ValueError("Логин: латинские буквы/цифры; пароль: минимум 10 символов")
    with db.session() as session:
        if session.scalar(select(User).where(User.username == username)):
            raise ValueError("Такой логин уже существует")
        user = User(username=username, display_name=display_name.strip() or username, password_hash=hasher.hash(password))
        session.add(user)
        session.flush()
        return user.id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user", "reset-password"])
    parser.add_argument("username")
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    password = getpass.getpass("Пароль (минимум 10 символов): ")
    if password != getpass.getpass("Повторите пароль: "):
        parser.error("Пароли не совпадают")
    db = Database(Settings())
    try:
        if args.command == "create-user":
            create_user(db, args.username, args.name, password)
        else:
            if len(password) < 10:
                raise ValueError("Пароль должен содержать минимум 10 символов")
            with db.session() as session:
                user = session.scalar(select(User).where(User.username == args.username.strip().lower()))
                if not user:
                    raise ValueError("Пользователь не найден")
                user.password_hash = hasher.hash(password)
                session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        print("Готово")
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
