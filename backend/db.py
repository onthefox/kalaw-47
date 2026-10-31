"""
Настройка подключения к PostgreSQL через SQLAlchemy
Оптимизировано для production с улучшенным connection pool
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://symbio:symbio@localhost:5432/symbio",
)

# Оптимизированный connection pool для production
engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # Увеличено с 5 до 20
    max_overflow=30,        # Увеличено с 10 до 30
    pool_pre_ping=True,     # Проверка соединения перед использованием
    pool_recycle=3600,      # Пересоздавать соединения через 1 час
    echo=False              # Выключить SQL логи в production
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """FastAPI-зависимость: предоставляет и закрывает сессию."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Создать все таблицы (для dev/CI)."""
    from .models import Base

    Base.metadata.create_all(bind=engine)
