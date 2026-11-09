"""
Настройка подключения к PostgreSQL через SQLAlchemy.
Для dev/CI включает лёгкую миграцию схемы (parent_id, link type).
"""

import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("symbio.db")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://symbio:symbio@localhost:5432/symbio",
)


def _create_engine(url: str):
    """Создаёт движок; для тестов (SQLite) — без PostgreSQL-пула."""
    if url.startswith("sqlite"):
        return create_engine(url)
    return create_engine(
        url,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """FastAPI-зависимость: предоставляет и закрывает сессию."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns(bind) -> None:
    """Лёгкая миграция: добавляет parent_id и type, если их ещё нет.

    PostgreSQL → ALTER TABLE ... ADD COLUMN IF NOT EXISTS.
    SQLite → попытка ALTER с игнорированием ошибки дубликата.
    Заодно удаляется старый уникальный индекс links (без type).
    """
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(text(
            "ALTER TABLE entities ADD COLUMN IF NOT EXISTS parent_id INTEGER"
        ))
        bind.execute(text(
            "ALTER TABLE links ADD COLUMN IF NOT EXISTS type VARCHAR(20) "
            "DEFAULT 'relates' NOT NULL"
        ))
        bind.execute(text("DROP INDEX IF EXISTS ix_links_source_target"))
    elif dialect == "sqlite":
        for ddl in (
            "ALTER TABLE entities ADD COLUMN parent_id INTEGER",
            "ALTER TABLE links ADD COLUMN type VARCHAR(20) DEFAULT 'relates' NOT NULL",
        ):
            try:
                bind.execute(text(ddl))
            except Exception:
                pass  # колонка уже существует
    bind.commit() if hasattr(bind, "commit") else None


def init_db() -> None:
    """Создать все таблицы и применить миграцию колонок (для dev/CI)."""
    from .models import Base

    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        _ensure_columns(conn)
        conn.commit()
