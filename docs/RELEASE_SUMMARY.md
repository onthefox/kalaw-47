# Итоговая сводка релиза — SymbioSystem v0.3

- **Ветка**: `release` @ `a2d192e`
- **Дата**: 2026-11-09
- **Тесты**: 374 passed, покрытие **91%** (5158 statements, 490 missed)
- **Открытые issues**: 0 (все 21 закрыты)

---

## Метрики

| Показатель | Значение |
| --- | --- |
| Тесты | 374 (все зелёные) |
| Покрытие | 91% |
| Рост тестовой базы | 312 → 353 (LLM, #9) → 374 (агенты, #3) |
| REST-эндпоинты | 23 |
| Агенты | 5 из 5 |
| Типы интентов | 12 |
| Типы событий observer | 11 |

---

## Цепочка merges в `release`

| Merge | Эпик | Ветка |
| --- | --- | --- |
| `c19afa8` | Базовый бэкенд: иерархия (#13), типизированные связи (#14), онтология (#15) | `agent/*` базовые |
| `62bbdfe` | LLM-ядро (`core/llm`): каскад провайдеров, rate limiter, cost tracker (#9) | `agent/llm-core` @ `8851339` |
| `cb45eea` | Агенты: ревизор + координатор, review-gate (#3, #1) | `agent/llm-core` @ `582e83b` |
| `a2d192e` | MindPalace UI: ванильный граф + карточка сущности (#4, #18, #19, #8) | `agent/kalaw-ui` |

---

## Что поставлено

### Ядро (SymbioCore / SymbioHive / SymbioFlow)
- 12 интентов: create, link, delete, query, evolve, rename/change, clone, merge, tag, prioritize, schedule, analyze
- Иерархия сущностей (parent/subtree/descendants, защита от циклов)
- Типизированные связи: relates, depends, blocks, contains, supports (циклы для depends/blocks)
- Confidence-скоринг: keyword + LLM blend, маршрутизация auto/review/clarification
- Контекстная память: сессии, TTL 5 минут, file/redis-бэкенды, разрешение местоимений

### LLM-слой (#9)
- Каскад провайдеров: openai → anthropic → google → rule-based fallback
- Rate limiter (token bucket), cost tracker с записью в БД
- Feedback loop: `POST /intent/feedback` + агрегированная статистика
- `GET /llm/status`, `GET /stats/llm`

### Автономные агенты (#3, #1)
- 5 агентов Flow Executor: observer, planner, executor/autogen, **reviewer**, **coordinator**
- **Ревизор** (`engine/reviewer/reviewer.py`): 5 аудитов целостности (висячие связи, дубли имён, циклы иерархии, пустые имена, orphan-отчёт) + review-gate
- **Координатор** (`engine/coordinator/coordinator.py`): реестр, диспетчеризация по интентам, эскалация
- Review-gate в SymbioFlow (шаг 5b): мутации с находками ревизора помечаются ошибкой
- API: `POST /review`, `GET /agents/status`
- 21 тест в `tests/test_agents_epic.py`

### Наблюдаемость (#16)
- Event bus + журнал изменений, 11 типов событий
- Alert-правила с порогами и окнами: `GET /events`, `GET /alerts`, `POST /alerts/rules`

### Планировщик (#17)
- Генерация планов с зависимостями, валидация (циклы, конфликты delete→use), sequentional/parallel выполнение, откат при ошибке

### MindPalace UI (vanilla, #4/#18/#19/#8)
- Ванильные ES-модули + vendored d3 v7.9.0 — сборка не требуется
- Интерактивный force-directed граф: drag, zoom, клик по сущности
- Карточка сущности: голова/свойства/таймлайн (ленивая загрузка `/events`), действия через `<dialog>` — переименование, теги, приоритет, связи, удаление
- Тёмная/светлая тема, `docs/DEMO.md` — сценарий демонстрации

---

## Ключевые закрытые issues

| Issue | Суть |
| --- | --- |
| #1 | Intent Engine эпик (12 интентов, confidence, контекст) |
| #3 | Эпик агентов: ревизор + координатор + review-gate |
| #4 | UI-эпик |
| #8 | Демо-документация |
| #9 | LLM-ядро: каскад, лимиты, стоимость |
| #13–#17, #20 | Иерархия, связи, онтология, observer, планировщик, autogen |
| #18, #19 | Интерактивный граф, карточка сущности |

---

## Отложено

- **SLO-бенчмарк LLM < 200 мс** — требует реальных API-ключей; отмечено в комментарии закрытия #1.

## Архив

Устаревшие документы (`IMPROVEMENTS.md`, `PERFORMANCE_SUMMARY.md`, `PROGRESS_SUMMARY.md`, `meta/revolution/*`) перемещены в [`docs/archive/`](archive/README.md). Папка `meta/` упразднена.
