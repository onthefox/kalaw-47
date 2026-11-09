# SymbioSystem — Симбиотическая AI-Экосистема

> **Не просто Neovim-плагин** — это полноценная симбиотическая AI-экосистема, где Neovim — лишь один из интерфейсов.

[![CI](https://github.com/onthefox/kalaw-47/actions/workflows/ci.yml/badge.svg)](https://github.com/onthefox/kalaw-47/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](docker-compose.yml)

---

## 🧩 Что это

**SymbioSystem** — это автономная симбиотическая экосистема нового поколения, которая:

- **Интерпретирует намерения** — превращает текстовые запросы в действия
- **Строит онтологию** — создаёт сущности, связи, эволюционирует
- **Автономно действует** — пайплайн: намерение → план → выполнение
- **Автогенерирует** — создаёт новые модули и расширяет систему
- **Визуализирует** — живой граф смыслов в реальном времени

Это **ядро AI-стартапа**, готовое к подаче в **Microsoft Founders Hub** и **GitHub for Startups**.

---

## 🏗️ Архитектура

```
kalaw-47 (SymbioSystem v0.3)
├── core/
│   ├── symbio_core/     # Ядро: интерпретация намерений (rules.py)
│   ├── symbio_hive/     # Рой: онтология, сущности, связи (hive.py)
│   └── llm/             # LLM-каскад: openai → anthropic → google → rules
├── engine/
│   ├── symbio_flow/     # Движок: приём → план → выполнение (flow.py)
│   ├── planner/         # Планировщик: генерация и валидация планов
│   ├── observer/        # Наблюдатель: события, журнал, алерты
│   ├── reviewer/        # Ревизор: аудиты целостности онтологии
│   ├── coordinator/     # Координатор: реестр и диспетчеризация агентов
│   └── autogen/         # Автоген: создание модулей по шаблонам
├── backend/             # FastAPI + SQLAlchemy
│   ├── main.py          # 23 REST-эндпоинта: интенты, онтология, агенты, LLM
│   ├── models.py        # ORM: Entity, Link, LLMUsage
│   └── db.py            # Подключение к БД
├── ui/mind_palace/      # Ванильный UI (ES-модули + vendored d3 v7.9.0)
│   ├── index.html       # Одна страница
│   ├── src/app.js       # Точка входа
│   ├── src/graph.js     # Force-directed граф
│   └── src/entityCard.js # Карточка сущности
├── docs/                # DEMO.md, RELEASE_SUMMARY.md, archive/
└── docker-compose.yml   # Полный стек одной командой
```

### Компоненты

| Компонент | Назначение | Статус |
|-----------|-----------|--------|
| **SymbioCore** | Интерпретация намерений (12 интентов) + confidence-скоринг | ✅ |
| **SymbioHive** | Онтология: иерархия, типизированные связи, защита от циклов | ✅ |
| **SymbioFlow** | Автономный движок с review-gate ревизора | ✅ |
| **LLM-слой** | Каскад провайдеров, rate limiter, cost tracker, feedback loop | ✅ |
| **Агенты** | 5 агентов: observer, planner, executor, reviewer, coordinator | ✅ |
| **Backend** | FastAPI (23 endpointа) + SQLAlchemy | ✅ |
| **MindPalace UI** | Ванильный force-directed граф + карточка сущности | ✅ |

---

## 🚀 Быстрый старт

### Docker (рекомендуется)

```bash
# Поднять весь стек
make up

# Или напрямую
docker-compose up --build
```

Откройте:
- **API Docs**: http://localhost:8000/docs
- **MindPalace UI**: http://localhost:3000

### Локальная разработка

```bash
# Бэкенд
cd backend
pip install -r requirements.txt
make backend   # uvicorn --reload на :8000

# Фронтенд (в другом терминале) — статика, сборка не нужна
make frontend  # python -m http.server 3000 на :3000
```

### Полезные команды

```bash
make down      # Остановить и удалить volumes
make migrate   # Инициализировать БД
make clean     # Полная очистка
```

---

## 🔌 API

| Method | Path | Описание |
|--------|------|----------|
| `POST` | `/intent` | Обработать текстовое намерение (LLM/rule-based) |
| `POST` | `/intent/feedback` | Подтвердить/отклонить интерпретацию |
| `GET` | `/entities` | Список сущностей (`?tree=`, пагинация) |
| `GET` | `/entities/{id}/descendants` | Потомки сущности |
| `POST` | `/entity` | Создать сущность напрямую |
| `POST` | `/entity/{id}/parent` | Назначить родителя |
| `GET` | `/links` | Список связей (фильтр по типу) |
| `POST` | `/link` | Создать типизированную связь |
| `GET` | `/ontology/export` | Экспорт онтологии (JSON/GraphML) |
| `POST` | `/ontology/import` | Импорт онтологии (merge/replace) |
| `GET` | `/events` | Журнал изменений |
| `GET` | `/alerts` | Сработавшие алерты |
| `POST` | `/alerts/rules` | Добавить alert-правило |
| `POST` | `/plan` | Сгенерировать и провалидировать план |
| `POST` | `/plan/execute` | Выполнить план (sequential/parallel) |
| `POST` | `/autogen` | Сгенерировать модуль по шаблону |
| `GET` | `/autogen/templates` | Список шаблонов autogen |
| `POST` | `/review` | Аудит онтологии агентом-ревизором |
| `GET` | `/agents/status` | Статус 5 агентов Flow Executor |
| `GET` | `/llm/status` | Статус LLM-провайдеров, лимиты, стоимость |
| `GET` | `/stats/llm` | Агрегированная статистика LLM |
| `GET` | `/stats` | Статистика экосистемы |
| `GET` | `/health` | Health check |

### Пример: отправка намерения

```bash
curl -X POST http://localhost:8000/intent \
  -H "Content-Type: application/json" \
  -d '{"intent": "создать Проект Адаптация"}'
```

Ответ:
```json
{
  "action": "create",
  "created": { "id": 1, "name": "Проект Адаптация" }
}
```

---

## 🎯 Позиционирование

**SymbioSystem — это не плагин для Neovim.** Это:

1. **AI-экосистема** — автономная система, которая интерпретирует намерения и действует
2. **Смысловой граф** — живая онтология, которая растёт и эволюционирует
3. **Платформа** — Neovim — лишь один из интерфейсов; API открыт для любых интеграций
4. **Стартап-продукт** — готов к подаче в Microsoft Founders Hub / GitHub for Startups

### Почему это важно

| Проблема | Решение SymbioSystem |
|----------|---------------------|
| AI-ассистенты — одноразовые запросы | Симбиотическая экосистема с памятью |
| Нет визуализации связей | MindPalace: живой граф смыслов |
| Статические онтологии | Растущая, эволюционирующая онтология |
| Нет автономности | Автономный движок: намерение → действие |

---

## 📊 Демо

### MindPalace UI

> Пошаговый сценарий демонстрации: [`docs/DEMO.md`](docs/DEMO.md)

### API в действии

```bash
# Создать сущность
curl -X POST "http://localhost:8000/intent" \
  -H "Content-Type: application/json" \
  -d '{"intent": "создать Проект SymbioSystem"}'

# Связать сущности
curl -X POST "http://localhost:8000/intent" \
  -H "Content-Type: application/json" \
  -d '{"intent": "связать SymbioSystem и piZdabolot"}'

# Посмотреть граф
curl http://localhost:8000/entities
curl http://localhost:8000/links
```

---

## 🛠️ Технологический стек

- **Backend**: Python 3.11+ · FastAPI · SQLAlchemy · PostgreSQL 15
- **Frontend**: ванильные ES-модули · vendored d3 v7.9.0 (сборка не требуется)
- **Инфраструктура**: Docker · docker-compose · GitHub Actions CI
- **Тестирование**: CI с PostgreSQL сервисом + Docker build проверка

---

## 📅 Roadmap

### ✅ Q2 2026 — MVP
- [x] SymbioCore v1 — интерпретация намерений
- [x] SymbioHive — онтология и связи
- [x] SymbioFlow — автономный пайплайн
- [x] Autogen — автогенерация
- [x] FastAPI backend (23 endpoints)
- [x] MindPalace UI (ванильные ES-модули + d3)
- [x] Docker + docker-compose
- [x] CI pipeline

### ✅ Q3 2026 — Автономные агенты и LLM
- [x] SymbioFlow autonomous agents (5 агентов)
- [x] Multi-agent coordination (координатор + review-gate)
- [x] Entity cards с деталями
- [x] LLM-powered intent parsing
- [ ] Real-time WebSocket updates (сейчас — polling `/events`)

### ✅ Q4 2026 — MindPalace 2.0 (частично)
- [x] Интерактивный граф
- [x] Временная шкала эволюции (таймлайн карточки)
- [x] Экспорт/импорт онтологии (JSON/GraphML)
- [ ] Плагины для VS Code, JetBrains
- [ ] API rate limiting + auth

### 🔮 Q1 2027 — SymbioSystem Cloud
- [ ] Managed SymbioSystem сервис
- [ ] Multi-tenant архитектура
- [ ] Billing + quotas
- [ ] SymbioSystem Marketplace
- [ ] Community-driven ontology

Полный отчёт о релизе: [`docs/RELEASE_SUMMARY.md`](docs/RELEASE_SUMMARY.md)

---

## 📄 Лицензии

| Компонент | Лицензия |
|-----------|----------|
| Всё | MIT © OnTheFox 2026 |

---

## 🤝 Вклад

Мы принимаем contributions! См. [`CONTRIBUTING.md`](CONTRIBUTING.md)

Кратко:
1. Fork → feature branch → PR
2. Тесты должны проходить (`make up`)
3. Conventional Commits

---

## 📞 Контакты

- **Репозиторий**: https://github.com/onthefox/kalaw-47
- **Issues**: https://github.com/onthefox/kalaw-47/issues
- **Автор**: OnTheFox
