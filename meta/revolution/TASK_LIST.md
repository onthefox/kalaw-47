# SymbioSystem — Task List для Реализации

> Сгенерировано на основе улучшенного Roadmap  
> Приоритет: Quick Wins → Must Have → Should Have

---

## 🎯 Quick Wins (Неделя 1-2) — ВЫСОКИЙ ПРИОРИТЕТ

### Задача 1: Search Bar в UI
**Файлы:** `ui/mind_palace/src/App.jsx`, `ui/mind_palace/src/Graph.jsx`  
**Сложность:** 1 день  
**Impact:** Высокий

**Чеклист:**
- [ ] Добавить state для search query
- [ ] Добавить input field в левую панель
- [ ] Фильтрация entities по name (case-insensitive)
- [ ] Подсветка найденных узлов на графе
- [ ] Кнопка "Clear search"

**Acceptance Criteria:**
- Поиск работает instant (client-side)
- Подсветка найденных узлов цветом
- Граф фильтруется в реальном времени

---

### Задача 2: Pytest + Unit Тесты
**Файлы:** `tests/`, `pytest.ini`, `requirements-dev.txt`  
**Сложность:** 2 дня  
**Impact:** Критичный

**Чеклист:**
- [ ] Создать `requirements-dev.txt` с pytest, pytest-cov
- [ ] Создать `pytest.ini` конфигурацию
- [ ] Написать тесты для `core/symbio_core/rules.py`:
  - [ ] Тест parse "создать X"
  - [ ] Тест parse "связать X и Y"
  - [ ] Тест parse "удалить X"
  - [ ] Тест parse "найти X"
  - [ ] Тест empty input
  - [ ] Тест unknown intent
- [ ] Написать тесты для `engine/autogen/autogen.py`:
  - [ ] Тест create entity
  - [ ] Тест create duplicate entity
  - [ ] Тест link entities
  - [ ] Тест delete entity
  - [ ] Тест query entity
- [ ] Настроить CI для запуска тестов
- [ ] Target coverage >60%

**Acceptance Criteria:**
- `pytest --cov` показывает >60% coverage
- Все тесты проходят в CI
- Tests run time <30s

---

### Задача 3: Redis Caching
**Файлы:** `backend/main.py`, `docker-compose.yml`, `backend/db.py`  
**Сложность:** 2 дня  
**Impact:** Высокий

**Чеклист:**
- [ ] Добавить Redis service в docker-compose
- [ ] Добавить `redis` в backend requirements
- [ ] Создать cache client wrapper
- [ ] Кэшировать GET /entities (TTL 30s)
- [ ] Кэшировать GET /links (TTL 30s)
- [ ] Invalidate cache при POST/DELETE
- [ ] Добавить cache hit/miss метрики

**Acceptance Criteria:**
- Cache hit уменьшает response time на 80%+
- TTL работает корректно
- Invalidation при изменениях

---

### Задача 4: Simple JWT Auth
**Файлы:** `backend/main.py`, `backend/auth.py` (новый), `backend/models.py`  
**Сложность:** 3 дня  
**Impact:** Критичный

**Чеклист:**
- [ ] Добавить `pyjwt` в requirements
- [ ] Создать модель User (id, email, password_hash)
- [ ] Создать endpoint POST /auth/register
- [ ] Создать endpoint POST /auth/login
- [ ] Генерировать JWT token при login
- [ ] Создать middleware для проверки токена
- [ ] Защитить endpoints (опционально для MVP)
- [ ] Добавить SECRET_KEY в .env

**Acceptance Criteria:**
- Регистрация работает
- Login возвращает токен
- Token валидируется в middleware
- Token expiry 24h

---

### Задача 5: JSON Export Endpoint
**Файлы:** `backend/main.py`  
**Сложность:** 1 день  
**Impact:** Средний

**Чеклист:**
- [ ] Создать GET /export/json endpoint
- [ ] Экспорт всех entities + links
- [ ] Включить metadata
- [ ] Content-Type: application/json
- [ ] Content-Disposition header для скачивания

**Acceptance Criteria:**
- Endpoint возвращает валидный JSON
- Файл можно скачать через браузер
- Все данные экспортируются

---

### Задача 6: Structured Logging
**Файлы:** `backend/main.py`, `backend/logging_config.py` (новый)  
**Сложность:** 2 дня  
**Impact:** Средний

**Чеклист:**
- [ ] Настроить JSON logging formatter
- [ ] Добавить correlation ID middleware
- [ ] Логировать все request/response
- [ ] Логировать errors с stack trace
- [ ] Добавить log levels (DEBUG, INFO, WARNING, ERROR)
- [ ] Конфигурируемый LOG_LEVEL из env

**Acceptance Criteria:**
- Логи в JSON формате
- Correlation ID присутствует в каждом логе
- Можно фильтровать по level

---

## 🚀 Q3 Must Have Tasks

### Задача 7: Агентская Архитектура
**Файлы:** `engine/agents/` (новая папка)  
**Сложность:** 5 дней  
**Impact:** Критичный

**Чеклист:**
- [ ] Создать базовый класс `Agent`
- [ ] Абстрактные методы: `observe()`, `plan()`, `execute()`, `review()`
- [ ] Реализовать `ObserverAgent`
- [ ] Реализовать `PlannerAgent`
- [ ] Реализовать `ExecutorAgent`
- [ ] Реализовать `ReviewerAgent`
- [ ] Создать `AgentCoordinator`
- [ ] Интегрировать с SymbioFlow

---

### Задача 8: LLM Integration
**Файлы:** `engine/llm/` (новая папка)  
**Сложность:** 5 дней  
**Impact:** Критичный

**Чеклист:**
- [ ] Создать интерфейс `LLMProvider`
- [ ] Реализовать `OpenAIProvider`
- [ ] Реализовать `AnthropicProvider`
- [ ] Реализовать fallback logic
- [ ] Создать `SemanticIntentParser`
- [ ] Добавить context memory (last N requests)
- [ ] Интегрировать с SymbioCore

---

### Задача 9: WebSocket Server
**Файлы:** `backend/websocket.py` (новый), `ui/mind_palace/src/api.js`  
**Сложность:** 3 дня  
**Impact:** Высокий

**Чеклист:**
- [ ] Добавить `websockets` library
- [ ] Создать `/ws` endpoint
- [ ] Broadcast при изменениях entities
- [ ] Subscription по типам событий
- [ ] Frontend WebSocket client
- [ ] Reconnection logic
- [ ] Remove polling из App.jsx

---

### Задача 10: Rate Limiting
**Файлы:** `backend/main.py`, `backend/middleware.py`  
**Сложность:** 2 дня  
**Impact:** Высокий

**Чеклист:**
- [ ] Интегрировать `slowapi`
- [ ] Настроить лимиты (100/min anon, 1000/min auth)
- [ ] Добавить rate limit headers
- [ ] Graceful degradation (429 response)

---

## 📋 Should Have Tasks

### Задача 11: Entity Cards 2.0
**Файлы:** `ui/mind_palace/src/EntityCard.jsx`  
**Сложность:** 3 дня

**Чеклист:**
- [ ] Показать full entity info
- [ ] История изменений
- [ ] Связанные сущности с превью
- [ ] Метрики (connections count, created at)
- [ ] Actions (edit, delete buttons)

---

### Задача 12: Search + Filters API
**Файлы:** `backend/main.py`  
**Сложность:** 2 дня

**Чеклист:**
- [ ] GET /entities?search=query
- [ ] GET /entities?type=...
- [ ] GET /entities?sort=name|created|connections
- [ ] GET /entities?order=asc|desc
- [ ] Fuzzy search support

---

### Задача 13: Export Formats
**Файлы:** `backend/export.py` (новый)  
**Сложность:** 3 дня

**Чеклист:**
- [ ] GET /export/json
- [ ] GET /export/graphml
- [ ] GET /export/dot
- [ ] GET /export/csv
- [ ] GET /export/svg (graph screenshot)

---

## 📅 Timeline

```
Week 1:
  ├─ Задача 1: Search Bar (1 day)
  ├─ Задача 2: Pytest setup + 5 tests (2 days)
  └─ Задача 5: JSON Export (1 day)

Week 2:
  ├─ Задача 2: Complete tests (1 day)
  ├─ Задача 3: Redis Caching (2 days)
  └─ Задача 6: Structured Logging (2 days)

Week 3:
  ├─ Задача 4: JWT Auth (3 days)
  └─ Задача 10: Rate Limiting (2 days)

Week 4:
  ├─ Задача 7: Agent Architecture (3 days)
  └─ Задача 8: LLM Integration (2 days)

Week 5-6:
  ├─ Задача 9: WebSocket (3 days)
  └─ Buffer + bug fixes
```

---

## 🔧 Начать выполнение

**Ready to start?** Begin with Task 1 (Search Bar) — lowest effort, highest immediate impact.
