"""
FastAPI — основной сервер Adapt SymbioSystem
Эндпоинты:
  POST /intent — обработать намерение
  GET  /entities — список всех сущностей
  GET  /links — список всех связей
  POST /entity — создать сущность напрямую
  POST /link — создать связь напрямую
  GET  /stats — статистика экосистемы
  GET  /health — проверка здоровья
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from backend.db import SessionLocal, get_db, init_db
from backend.models import Entity, Link
from engine.symbio_flow import handle_intent
from core.symbio_hive import stats as hive_stats, get_entities as hive_entities, get_links as hive_links


# --- Pydantic схемы ---

class IntentRequest(BaseModel):
    intent: str


class IntentResponse(BaseModel):
    action: str
    created: Any | None = None
    deleted: str | None = None
    entity: Any | None = None
    connections: list[str] | None = None
    error: str | None = None
    intent: dict | None = None


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация БД при старте."""
    init_db()
    yield


app = FastAPI(
    title="Adapt SymbioSystem",
    description="Симбиотическая экосистема с автономным движком и живым графом смыслов",
    version="0.2.0",  # Обновлена версия после оптимизаций
    lifespan=lifespan,
)


# --- Эндпоинты ---

@app.post("/intent", response_model=IntentResponse)
def post_intent(req: IntentRequest, db: Session = Depends(get_db)):
    """Принять текстовое намерение → интерпретировать → выполнить → вернуть результат."""
    result = handle_intent(req.intent, db)
    if "error" in result and result.get("action") == "unknown":
        raise HTTPException(status_code=400, detail=result.get("error", "Неизвестное действие"))
    return result


@app.get("/entities")
def list_entities(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Список всех сущностей в графе с пагинацией и eager loading."""
    # Eager loading для предотвращения N+1 запросов
    entities = (
        db.query(Entity)
        .options(selectinload(Entity.source_links), selectinload(Entity.target_links))
        .offset(skip)
        .limit(limit)
        .all()
    )
    total = db.query(Entity).count()
    return {
        "items": [e.to_dict() for e in entities],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total
    }


@app.get("/links")
def list_links(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Список всех связей в графе с пагинацией."""
    links = (
        db.query(Link)
        .offset(skip)
        .limit(limit)
        .all()
    )
    total = db.query(Link).count()
    return {
        "items": [l.to_dict() for l in links],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total
    }


@app.post("/entity")
def create_entity(name: str, db: Session = Depends(get_db)):
    """Создать сущность напрямую (без парсинга намерения)."""
    existing = db.query(Entity).filter_by(name=name).first()
    if existing:
        return {"exists": existing.to_dict()}
    entity = Entity(name=name)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return {"created": entity.to_dict()}


@app.post("/link")
def create_link(source: str, target: str, db: Session = Depends(get_db)):
    """Создать связь между двумя сущностями по именам."""
    src = db.query(Entity).filter_by(name=source).first()
    tgt = db.query(Entity).filter_by(name=target).first()
    if not src or not tgt:
        missing = []
        if not src:
            missing.append(source)
        if not tgt:
            missing.append(target)
        raise HTTPException(status_code=404, detail=f"Сущность не найдена: {', '.join(missing)}")
    existing = db.query(Link).filter_by(source_id=src.id, target_id=tgt.id).first()
    if existing:
        return {"exists": existing.to_dict()}
    link = Link(source_id=src.id, target_id=tgt.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"created": {"id": link.id, "source": src.name, "target": tgt.name}}


@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Статистика экосистемы."""
    return {
        "entities": db.query(Entity).count(),
        "links": db.query(Link).count(),
    }


@app.get("/health")
def health_check():
    """Проверка здоровья API."""
    return {"status": "ok", "service": "Adapt SymbioSystem"}
