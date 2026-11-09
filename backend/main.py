"""
FastAPI — основной сервер Adapt SymbioSystem.

Эндпоинты:
  POST /intent — намерение с сессиями, confidence и LLM (fallback rule-based)
  POST /intent/feedback — feedback loop подтверждений
  GET  /entities[?tree=true&root_id=&max_depth=] — список/дерево сущностей
  GET  /links[?type=depends] — связи с фильтром по типу
  POST /entity — создать сущность (опционально parent_id)
  POST /link — создать типизированную связь (cycle check для depends/blocks)
  GET  /ontology/export?format=json|graphml — экспорт онтологии
  POST /ontology/import?mode=replace|merge — импорт онтологии
  GET  /events — журнал изменений наблюдателя (фильтры)
  GET  /alerts — сработавшие пороги
  POST /plan — сгенерировать план из намерений
  POST /plan/execute — выполнить план (sequential/parallel)
  POST /autogen — сгенерировать модуль по шаблону
  POST /review — аудит онтологии агентом-ревизором (issue #3)
  GET  /agents/status — реестр 5 агентов Flow Executor (issue #3)
  GET  /llm/status — провайдеры, лимиты, стоимость
  GET  /stats/llm — агрегированная стоимость LLM (issue #9)
  GET  /stats — статистика экосистемы
  GET  /health — проверка здоровья
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db import get_db, init_db
from backend.graph import build_tree, creates_cycle, get_descendants, get_subtree
from backend.models import Entity, Link, LLMUsage
from backend.ontology import (
    apply_import,
    export_graphml,
    export_json,
    parse_import_payload,
    validate_payload,
)
from core.symbio_hive.links import LinkType, is_cycle_checked, normalize_link_type
from core.symbio_core.confidence import feedback_store
from core.symbio_core.context import ContextMemory, context_memory
from engine.autogen import TEMPLATE_TYPES, autogen_handle, generate_module
from engine.coordinator import coordinator
from engine.llm import llm_chain
from engine.observer import observer, publish_change
from engine.reviewer import reviewer
from engine.planner import Plan, execute_plan, generate_plan, validate_plan
from engine.symbio_flow import handle_intent

logger = logging.getLogger("symbio.api")


# --- Pydantic схемы ---

class IntentRequest(BaseModel):
    intent: str
    session_id: str | None = None
    use_context: bool = True
    use_llm: bool = True


class IntentResponse(BaseModel):
    """Ответ /intent с LLM-атрибуцией (issue #9, задача 3).

    extra=allow: сохраняет свободные поля пайплайна (route, intent, ...).
    """

    model_config = {"extra": "allow"}

    action: str | None = None
    provider: str | None = None
    confidence: float | None = None
    tokens_used: int | None = None


class FeedbackRequest(BaseModel):
    intent_id: str
    action: str
    accepted: bool


class CreateEntityRequest(BaseModel):
    name: str
    parent_id: int | None = None


class CreateLinkRequest(BaseModel):
    source: str
    target: str
    type: str = LinkType.RELATES.value


class ImportRequest(BaseModel):
    data: Any = None
    entities: list[dict[str, Any]] | None = None
    links: list[dict[str, Any]] | None = None
    format: str | None = None
    mode: str = "merge"


class PlanRequest(BaseModel):
    intents: list[str | dict[str, Any]] = Field(..., description="Намерения (текст или dict)")
    goal: str = ""


class PlanExecuteRequest(BaseModel):
    intents: list[str | dict[str, Any]] = Field(..., description="Намерения (текст или dict)")
    goal: str = ""
    parallel: bool = False


class AutogenRequest(BaseModel):
    template: str
    name: str
    type: str = "service"
    dependencies: list[str] = []


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Adapt SymbioSystem",
    description="Симбиотическая экосистема с автономным движком и живым графом смыслов",
    version="0.3.0",
    lifespan=lifespan,
)


# --- Намерения ---

@app.post("/intent", response_model=IntentResponse)
def post_intent(req: IntentRequest, db: Session = Depends(get_db)):
    """Намерение → контекст → LLM/rule-based → confidence → выполнение."""
    if not req.intent or not req.intent.strip():
        raise HTTPException(status_code=400, detail="Пустое намерение")
    result = handle_intent(
        req.intent,
        db,
        session_id=req.session_id,
        use_context=req.use_context,
        use_llm=req.use_llm,
        context_memory=context_memory,
        llm_chain=llm_chain,
    )
    return result


@app.post("/intent/feedback")
def post_intent_feedback(req: FeedbackRequest):
    """Feedback loop: пользователь подтверждает/отклоняет интерпретацию."""
    entry = feedback_store.record(
        action=req.action, accepted=req.accepted, intent_text=None
    )
    return {"recorded": True, "entry": {k: v for k, v in entry.items()}, "stats": feedback_store.stats()}


# --- Сущности и иерархия ---

@app.get("/entities")
def list_entities(
    tree: bool = Query(False, description="Вернуть дерево вместо плоского списка"),
    root_id: int | None = Query(None, description="Корень поддерева"),
    max_depth: int | None = Query(None, ge=0, le=50, description="Ограничение глубины"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Список сущностей; ?tree=true — иерархическое дерево (issue #13)."""
    if tree:
        if root_id is not None:
            root = db.query(Entity).filter_by(id=root_id).first()
            if not root:
                raise HTTPException(status_code=404, detail=f"Корень id={root_id} не найден")
            items = [get_subtree(db, root, max_depth)]
        else:
            entities = db.query(Entity).all()
            items = build_tree([e.to_dict() for e in entities])
        return {"items": items, "mode": "tree"}

    query = db.query(Entity).order_by(Entity.id)
    total = query.count()
    entities = query.offset(skip).limit(limit).all()
    return {
        "items": [e.to_dict() for e in entities],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total,
    }


@app.get("/entities/{entity_id}/descendants")
def list_descendants(
    entity_id: int,
    max_depth: int | None = Query(None, ge=0, le=50),
    db: Session = Depends(get_db),
):
    """Потомки сущности (depth-limited, issue #13)."""
    entity = db.query(Entity).filter_by(id=entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail=f"Сущность id={entity_id} не найдена")
    descendants = get_descendants(db, entity, max_depth)
    return {"items": [d.to_dict() for d in descendants], "count": len(descendants)}


@app.post("/entity")
def create_entity(req: CreateEntityRequest, db: Session = Depends(get_db)):
    """Создать сущность напрямую (опционально с родителем)."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    if req.parent_id is not None:
        parent = db.query(Entity).filter_by(id=req.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail=f"Родитель id={req.parent_id} не найден")
    existing = db.query(Entity).filter_by(name=name).first()
    if existing:
        return {"exists": existing.to_dict()}
    entity = Entity(name=name, parent_id=req.parent_id)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    publish_change("entity.created", entity=name, data={"id": entity.id})
    return {"created": entity.to_dict()}


@app.post("/entity/{entity_id}/parent")
def set_entity_parent(entity_id: int, parent_id: int | None = None, db: Session = Depends(get_db)):
    """Назначить/снять родителя (иерархия, issue #13)."""
    entity = db.query(Entity).filter_by(id=entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail=f"Сущность id={entity_id} не найдена")
    if parent_id is None:
        entity.parent_id = None
        db.commit()
        return {"updated": entity.to_dict()}
    if parent_id == entity_id:
        raise HTTPException(status_code=400, detail="Сущность не может быть родителем самой себя")
    parent = db.query(Entity).filter_by(id=parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail=f"Родитель id={parent_id} не найден")
    # Проверка цикла: подняться по предкам
    walker = parent
    while walker is not None:
        if walker.id == entity.id:
            raise HTTPException(status_code=400, detail="Назначение родителя создаст цикл")
        walker = walker.parent
    entity.parent_id = parent_id
    db.commit()
    db.refresh(entity)
    return {"updated": entity.to_dict()}


# --- Связи ---

@app.get("/links")
def list_links(
    type: str | None = Query(None, alias="type", description="Фильтр по типу связи"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Список связей с фильтрацией по типу (issue #14)."""
    query = db.query(Link)
    if type is not None:
        normalized = normalize_link_type(type)
        if type and normalized != type.lower() and type.lower() not in LinkType.values():
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестный тип связи '{type}'. Доступно: {', '.join(LinkType.values())}",
            )
        query = query.filter(Link.type == normalized)
    total = query.count()
    links = query.offset(skip).limit(limit).all()
    return {
        "items": [l.to_dict() for l in links],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total,
    }


@app.post("/link")
def create_link(req: CreateLinkRequest, db: Session = Depends(get_db)):
    """Создать типизированную связь. Для depends/blocks — проверка циклов (issue #14)."""
    link_type = normalize_link_type(req.type)
    if req.type and req.type.lower() not in LinkType.values():
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный тип связи '{req.type}'. Доступно: {', '.join(LinkType.values())}",
        )
    src = db.query(Entity).filter_by(name=req.source.strip()).first()
    tgt = db.query(Entity).filter_by(name=req.target.strip()).first()
    if not src or not tgt:
        missing = [n for n, e in ((req.source, src), (req.target, tgt)) if not e]
        raise HTTPException(status_code=404, detail=f"Сущность не найдена: {', '.join(missing)}")
    if src.id == tgt.id:
        raise HTTPException(status_code=400, detail="Нельзя связать сущность с самой собой")
    if is_cycle_checked(link_type) and creates_cycle(db, src.id, tgt.id, link_type):
        raise HTTPException(
            status_code=400,
            detail=f"Связь '{link_type}' {src.name} → {tgt.name} создаст цикл",
        )
    existing = (
        db.query(Link).filter_by(source_id=src.id, target_id=tgt.id, type=link_type).first()
    )
    if existing:
        return {"exists": existing.to_dict()}
    link = Link(source_id=src.id, target_id=tgt.id, type=link_type)
    db.add(link)
    db.commit()
    db.refresh(link)
    publish_change("link.created", entity=src.name, data={"target": tgt.name, "type": link_type})
    return {"created": {"id": link.id, "source": src.name, "target": tgt.name, "type": link_type}}


# --- Онтология ---

@app.get("/ontology/export")
def ontology_export(
    format: str = Query("json", pattern="^(json|graphml)$"),
    db: Session = Depends(get_db),
):
    """Экспорт онтологии в JSON или GraphML (issue #15)."""
    if format == "graphml":
        xml = export_graphml(db)
        return Response(content=xml, media_type="application/xml")
    return export_json(db)


@app.post("/ontology/import")
def ontology_import(req: ImportRequest, mode: str = Query("merge", pattern="^(replace|merge)$"), db: Session = Depends(get_db)):
    """Импорт онтологии: JSON-payload или GraphML (issue #15)."""
    try:
        if req.entities is not None:
            payload = {"entities": req.entities, "links": req.links or []}
        else:
            payload = parse_import_payload(req.data if req.data is not None else req.model_dump())
        clean, errors = validate_payload(payload)
        if errors and not clean["entities"]:
            raise HTTPException(status_code=400, detail={"errors": errors})
        stats = apply_import(db, clean, mode=req.mode or mode)
        return {"imported": stats, "validation_errors": errors}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- Наблюдатель ---

@app.get("/events")
def list_events(
    event_type: str | None = Query(None, description="Паттерн типа события, напр. 'entity.*'"),
    entity: str | None = Query(None),
    since: float | None = Query(None, description="Unix timestamp"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Журнал изменений с фильтрацией (issue #16)."""
    return {"items": observer.get_log(event_type=event_type, entity=entity, since_ts=since, limit=limit)}


@app.get("/alerts")
def list_alerts(limit: int = Query(50, ge=1, le=500)):
    """Сработавшие alert-пороги (issue #16)."""
    return {"items": observer.get_alerts(limit=limit), "rules": observer.list_rules()}


@app.post("/alerts/rules")
def add_alert_rule(
    pattern: str = Query(..., description="Паттерн события, напр. 'entity.deleted'"),
    threshold: int = Query(1, ge=1),
    window: float = Query(60.0, gt=0),
):
    """Добавить правило порогового оповещения (issue #16)."""
    rule_id = observer.add_rule(pattern, threshold=threshold, window=window)
    return {"rule_id": rule_id, "rules": observer.list_rules()}


# --- Планировщик ---

@app.post("/plan")
def create_plan(req: PlanRequest):
    """Сгенерировать и провалидировать план (issue #17)."""
    plan = generate_plan(req.intents, req.goal)
    problems = validate_plan(plan)
    return {"valid": not problems, "problems": problems, "plan": plan.to_dict()}


@app.post("/plan/execute")
def execute_plan_endpoint(req: PlanExecuteRequest, db: Session = Depends(get_db)):
    """Сгенерировать и выполнить план; при ошибке — откат (issue #17)."""
    plan = generate_plan(req.intents, req.goal)
    problems = validate_plan(plan)
    if problems:
        return JSONResponse(status_code=400, content={"valid": False, "problems": problems, "plan": plan.to_dict()})
    session_factory = None
    if req.parallel:
        from backend.db import SessionLocal

        session_factory = SessionLocal
    result = execute_plan(plan, db, parallel=req.parallel, session_factory=session_factory)
    return result


# --- Autogen ---

@app.post("/autogen")
def autogen_endpoint(req: AutogenRequest, db: Session = Depends(get_db)):
    """Сгенерировать модуль по шаблону и зарегистрировать в Hive (issue #20)."""
    result = generate_module(
        req.template,
        req.name,
        db=db,
        type_=req.type,
        dependencies=req.dependencies,
    )
    if not result["valid"] and result["errors"]:
        raise HTTPException(status_code=400, detail=result["errors"])
    if result["elapsed_ms"] > 5000:
        logger.warning("autogen slow: %dms", result["elapsed_ms"])
    return result


@app.get("/autogen/templates")
def autogen_templates():
    """Список доступных шаблонов (issue #20)."""
    return {"templates": list(TEMPLATE_TYPES)}


# --- Агенты (ревизор + координатор, issue #3) ---

@app.post("/review")
def run_review(db: Session = Depends(get_db)):
    """Аудит целостности онтологии агентом-ревизором (issue #3)."""
    return reviewer.audit(db)


@app.get("/agents/status")
def agents_status():
    """Реестр 5 агентов Flow Executor + статус ревизора (issue #3)."""
    status = coordinator.status()
    status["reviewer"] = reviewer.stats()
    return status


# --- LLM ---

@app.get("/llm/status")
def llm_status():
    """Статус LLM-провайдеров, лимитов и стоимости (issue #9)."""
    return {
        "available": llm_chain.available,
        "last_provider": llm_chain.last_provider,
        "providers": [
            {"name": p.name, "available": p.available, "model": p.model}
            for p in llm_chain.providers
        ],
        "rate_limit": {"max_calls": llm_chain.rate_limiter.max_calls, "period": llm_chain.rate_limiter.period},
        "cost": llm_chain.cost_tracker.usage(),
    }


# --- Статистика ---

@app.get("/stats/llm")
def llm_stats(db: Session = Depends(get_db)):
    """Агрегированная статистика стоимости LLM (issue #9, задача 3)."""
    rows = db.query(LLMUsage).all()
    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = agg.setdefault(
            row.provider,
            {
                "provider": row.provider,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost": 0.0,
                "success": 0,
                "failed": 0,
            },
        )
        entry["requests"] += 1
        entry["input_tokens"] += row.input_tokens or 0
        entry["output_tokens"] += row.output_tokens or 0
        entry["estimated_cost"] = round(entry["estimated_cost"] + (row.estimated_cost or 0.0), 6)
        entry["success" if row.success else "failed"] += 1
    providers = sorted(agg.values(), key=lambda e: e["provider"])
    return {
        "total_requests": sum(e["requests"] for e in providers),
        "total_estimated_cost": round(sum(e["estimated_cost"] for e in providers), 6),
        "total_input_tokens": sum(e["input_tokens"] for e in providers),
        "total_output_tokens": sum(e["output_tokens"] for e in providers),
        "providers": providers,
    }


@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Статистика экосистемы."""
    from sqlalchemy import func

    type_counts = dict(
        db.query(Link.type, func.count(Link.id)).group_by(Link.type).all()
    )
    roots = db.query(Entity).filter(Entity.parent_id.is_(None)).count()
    return {
        "entities": db.query(Entity).count(),
        "links": db.query(Link).count(),
        "links_by_type": type_counts,
        "root_entities": roots,
        "events": observer.stats(),
    }


@app.get("/health")
def health_check():
    """Проверка здоровья API."""
    return {"status": "ok", "service": "Adapt SymbioSystem"}
