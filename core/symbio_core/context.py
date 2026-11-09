"""
Контекстная память намерений (issue #10).

Возможности:
  - Сессии по session_id
  - Окно последних N намерений
  - Разрешение ссылок (он, это, тот ...) на последнюю упомянутую сущность
  - TTL: контекст истекает после 5 минут неактивности
  - Сериализация: память (по умолчанию), файл, Redis
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("symbio.context")

DEFAULT_TTL_SECONDS = 300  # 5 минут
DEFAULT_WINDOW = 10

REFERENCE_WORDS = {
    "он",
    "она",
    "оно",
    "они",
    "это",
    "эта",
    "этот",
    "тот",
    "та",
    "его",
    "её",
    "их",
    "него",
    "ним",
    "нее",
}


class ContextBackend(Protocol):
    """Бэкенд хранения сессий: load/save/delete по session_id."""

    def load(self, session_id: str) -> dict[str, Any] | None: ...

    def save(self, session_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> None: ...


class MemoryBackend:
    """Хранение в памяти процесса."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def load(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            raw = self._data.get(session_id)
            return json.loads(json.dumps(raw)) if raw is not None else None

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._data[session_id] = json.loads(json.dumps(data))

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)


class FileBackend:
    """Хранение в JSON-файлах внутри каталога."""

    def __init__(self, directory: str | os.PathLike[str] = ".symbio_context") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)
        return self.directory / f"{safe}.json"

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("context file corrupted: %s", path)
                return None

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        path = self._path(session_id)
        with self._lock:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


class RedisBackend:
    """Хранение в Redis. Клиент передаётся извне (redis.Redis).

    Используется SETEX с TTL, поэтому протухание контекста делает сам Redis;
   MemoryBackend-совместимый интерфейс.
    """

    PREFIX = "symbio:context:"

    def __init__(self, client: Any, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self.client = client
        self.ttl = ttl

    def _key(self, session_id: str) -> str:
        return f"{self.PREFIX}{session_id}"

    def load(self, session_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(session_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        setter = getattr(self.client, "setex", None)
        if setter is not None:
            setter(self._key(session_id), self.ttl, payload)
        else:
            self.client.set(self._key(session_id), payload)

    def delete(self, session_id: str) -> None:
        self.client.delete(self._key(session_id))


class ContextMemory:
    """Память контекста: окно намерений по сессиям + разрешение ссылок."""

    def __init__(
        self,
        backend: ContextBackend | None = None,
        ttl: float = DEFAULT_TTL_SECONDS,
        window: int = DEFAULT_WINDOW,
    ) -> None:
        self.backend = backend or MemoryBackend()
        self.ttl = ttl
        self.window = window

    # --- Внутреннее ---

    def _load(self, session_id: str) -> dict[str, Any]:
        data = self.backend.load(session_id)
        if not data or not isinstance(data.get("entries"), list):
            return {"entries": []}
        return data

    def _prune(self, data: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        fresh = [
            e
            for e in data["entries"]
            if float(e.get("ts", 0)) + self.ttl > now
        ]
        data["entries"] = fresh[-self.window :]
        return data

    # --- Публичный API ---

    def remember(
        self, session_id: str, parsed: dict[str, Any], ts: float | None = None
    ) -> dict[str, Any]:
        """Запомнить разобранное намерение в контексте сессии."""
        data = self._load(session_id)
        data = self._prune(data, ts)
        entry = {
            "ts": time.time() if ts is None else ts,
            "intent": {k: v for k, v in parsed.items()},
        }
        data["entries"].append(entry)
        data["entries"] = data["entries"][-self.window :]
        self.backend.save(session_id, data)
        return entry

    def get(self, session_id: str) -> list[dict[str, Any]]:
        """Неистёкшие записи контекста (от старых к свежим)."""
        data = self._load(session_id)
        data = self._prune(data)
        return data["entries"]

    def last_entity(self, session_id: str) -> str | None:
        """Последняя упомянутая сущность в сессии (для ссылок он/это/тот)."""
        for entry in reversed(self.get(session_id)):
            intent = entry.get("intent", {})
            created = intent.get("created")
            if isinstance(created, dict) and created.get("name"):
                return str(created["name"])
            entities = intent.get("entities")
            if isinstance(entities, list) and entities:
                return str(entities[-1])
            entity = intent.get("entity")
            if entity:
                return str(entity)
            deleted = intent.get("deleted")
            if deleted:
                return str(deleted)
        return None

    def resolve(self, session_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
        """Заменить местоимения (он/это/тот...) на сущность из контекста.

        Возвращает копию parsed с полями resolved_references и/или
        unresolved_reference.
        """
        resolved = dict(parsed)
        last = self.last_entity(session_id)
        touched: list[str] = []

        if "entity" in resolved and resolved["entity"] in REFERENCE_WORDS:
            if last:
                resolved["entity"] = last
                touched.append(resolved["entity"])
            else:
                resolved["unresolved_reference"] = resolved["entity"]

        if isinstance(resolved.get("entities"), list):
            new_entities: list[str] = []
            unresolved = False
            for name in resolved["entities"]:
                if name in REFERENCE_WORDS:
                    if last:
                        new_entities.append(last)
                        touched.append(last)
                    else:
                        new_entities.append(name)
                        unresolved = True
                else:
                    new_entities.append(name)
            resolved["entities"] = new_entities
            if unresolved and "unresolved_reference" not in resolved:
                resolved["unresolved_reference"] = "reference"

        if touched:
            resolved["resolved_references"] = touched
        return resolved

    def clear_expired(self, now: float | None = None) -> int:
        """Удалить истёкшие записи. Возвращает количество удалённых."""
        now = time.time() if now is None else now
        data = self._load("__clear_probe__")
        return len(self._prune(data, now)["entries"]) if data["entries"] else 0

    def clear(self, session_id: str | None = None) -> None:
        """Очистить одну сессию или пометить всю память пустой."""
        if session_id is None:
            raise ValueError("Укажите session_id для очистки")
        self.backend.save(session_id, {"entries": []})

    # --- Сериализация ---

    def export(self, session_id: str) -> dict[str, Any]:
        """Экспортировать контекст сессии (для бэкапа/трансфера)."""
        return {"session_id": session_id, **self._load(session_id)}

    def import_(self, session_id: str, data: dict[str, Any]) -> None:
        """Импортировать контекст сессии из export()."""
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Ожидается список entries")
        self.backend.save(session_id, {"entries": entries[-self.window :]})


# Глобальная память контекста для flow/API
context_memory = ContextMemory()
