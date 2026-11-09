"""
SymbioFlow — обработка намерений (полный цикл).

Пайплайн (issues #9, #10, #11):
  текст → разрешение ссылок по контексту сессии → LLM-цепочка
  (fallback на rule-based парсер) → confidence scoring → маршрутизация
  (>0.9 auto, 0.7–0.9 review, <0.7 уточняющий вопрос) → выполнение через
  autogen → запоминание в контексте → событие наблюдателю.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from typing import Any

from core.llm.orchestrator import LLMOrchestrator
from core.symbio_core import interpret_intent
from core.symbio_core.confidence import blend, score
from core.symbio_core.context import ContextMemory, context_memory
from engine.autogen import autogen_handle
from engine.llm import llm_chain
from engine.observer import publish_change

logger = logging.getLogger("symbio.flow")

_core_orchestrator: LLMOrchestrator | None = None


def get_core_orchestrator() -> LLMOrchestrator:
    """Ленивый singleton оркестратора core/llm (issue #9, задача 3)."""
    global _core_orchestrator
    if _core_orchestrator is None:
        _core_orchestrator = LLMOrchestrator()
    return _core_orchestrator


def reset_core_orchestrator() -> None:
    """Сброс singleton (для тестов)."""
    global _core_orchestrator
    _core_orchestrator = None


def _run_async(coro):
    """Выполнить корутину из синхронного кода (handle_intent остаётся sync)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Мы внутри работающего event loop — уходим в отдельный поток
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def handle_intent(
    text: str,
    db,
    session_id: str | None = None,
    use_context: bool = True,
    use_llm: bool = True,
    context_memory: ContextMemory = context_memory,
    llm_chain=llm_chain,
    orchestrator: LLMOrchestrator | None = None,
) -> dict[str, Any]:
    """Полный цикл: текст → парсинг → оценка → выполнение → результат.

    LLM-путь (issue #9, задача 3): при настроенных провайдерах текст идёт
    через LLMOrchestrator.interpret_with_fallback (OpenAI → Anthropic →
    Google → rule-based); иначе — legacy engine.llm-цепочка (совместимость).
    """
    intent_id = uuid.uuid4().hex[:12]
    tokens_used = 0

    # 1. Парсинг: core/llm оркестратор (LLM + fallback) или rule-based
    core_result = None
    if orchestrator is None and use_llm:
        orchestrator = get_core_orchestrator() if get_core_orchestrator().has_available_providers() else None
    if use_llm and orchestrator is not None and orchestrator.has_available_providers():
        core_result = _run_async(orchestrator.interpret_with_fallback(text, db))
        if core_result.provider != "rule-based":
            parsed = dict(core_result.data)
            parsed["confidence"] = core_result.confidence
            tokens_used = core_result.input_tokens + core_result.output_tokens
        else:
            parsed = interpret_intent(text)
    else:
        parsed = interpret_intent(text)

    # 2. Контекст: разрешение ссылок он/это/тот
    if use_context and session_id:
        parsed = context_memory.resolve(session_id, parsed)
        if parsed.get("unresolved_reference"):
            result = {
                "action": "clarification",
                "needs_clarification": True,
                "confidence": parsed.get("confidence", 0.0),
                "question": (
                    f"Уточните, к какой сущности относится "
                    f"«{parsed['unresolved_reference']}»"
                ),
                "intent_id": intent_id,
                "session_id": session_id,
                "intent": parsed,
            }
            publish_change("intent.clarification", data={"intent_id": intent_id})
            return result

    # 3. LLM-вероятность (legacy engine.llm; пропускается, если core-оркестратор
    # уже обработал запрос выше)
    llm_probability: float | None = None
    llm_provider: str | None = None
    if core_result is not None:
        llm_probability = core_result.confidence
        llm_provider = core_result.provider if core_result.provider != "rule-based" else None
    elif use_llm and llm_chain.available:
        chain_result = llm_chain.interpret(text)
        if chain_result:
            llm_probability = float(chain_result.get("probability", 0.5))
            llm_provider = chain_result.get("provider")
            # Если rule-based не справился, но LLM дал действие — используем его
            if parsed.get("action") == "unknown" and chain_result["parsed"].get("action"):
                llm_parsed = dict(chain_result["parsed"])
                llm_parsed.pop("probability", None)
                llm_parsed.pop("provider", None)
                parsed = llm_parsed
                parsed["confidence"] = llm_probability

    # 4. Confidence scoring + маршрутизация
    parsed = score(parsed, llm_probability)
    confidence = parsed.get("confidence", 0.0)
    route = parsed.get("route", "clarification")

    if parsed.get("action") == "unknown" or route == "clarification":
        result = {
            "action": parsed.get("action", "unknown"),
            "needs_clarification": True,
            "confidence": confidence,
            "route": route,
            "question": (
                f"Не уверен, что вы имеете в виду (уверенность {confidence}). "
                "Уточните действие: создать, связать, удалить, найти, изменить, "
                "клонировать, объединить, тег, приоритет, запланировать, анализ"
            ),
            "intent_id": intent_id,
            "session_id": session_id,
            "intent": parsed,
        }
        if llm_provider:
            result["llm_provider"] = llm_provider
            result["provider"] = llm_provider
            result["tokens_used"] = tokens_used
        publish_change(
            "intent.clarification",
            data={"intent_id": intent_id, "confidence": confidence},
        )
        return result

    # 5. Выполнение
    result = autogen_handle(parsed, db)
    result["intent"] = parsed
    result["confidence"] = confidence
    result["route"] = route
    result["review_required"] = route == "review"
    result["intent_id"] = intent_id
    result["session_id"] = session_id
    if llm_provider:
        result["llm_provider"] = llm_provider
        result["provider"] = llm_provider
        result["tokens_used"] = tokens_used

    # 5b. Review-gate: мутацию проверяет ревизор (issue #3, 5 агентов)
    try:
        from engine.reviewer import reviewer as reviewer_agent

        finding = reviewer_agent.review_mutation(result)
        if finding:
            result["review"] = {"healthy": False, "findings": [finding]}
    except ImportError:  # pragma: no cover
        pass

    # 6. Контекст: запомнить намерение (с результатом для ссылок)
    if use_context and session_id:
        stored = dict(parsed)
        stored["created"] = result.get("created")
        stored["deleted"] = result.get("deleted")
        context_memory.remember(session_id, stored)

    publish_change(
        "intent.processed",
        entity=parsed.get("entity") or parsed.get("target"),
        data={"intent_id": intent_id, "action": parsed["action"], "confidence": confidence},
    )
    return result


def record_feedback(intent_id: str, action: str, accepted: bool) -> dict[str, Any]:
    """Feedback loop: подтверждение/отклонение интерпретации пользователем."""
    from core.symbio_core.confidence import feedback_store

    return feedback_store.record(action=action, accepted=accepted, intent_text=None, confidence=None)
