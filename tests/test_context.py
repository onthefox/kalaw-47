"""
Issue #10: контекстная память — сессии, окно, ссылки, TTL, сериализация.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.symbio_core.context import (
    ContextMemory,
    FileBackend,
    MemoryBackend,
    RedisBackend,
)


class TestSessionsAndWindow:
    def test_remember_and_get(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "проект"})
        entries = memory.get("s1")
        assert len(entries) == 1
        assert entries[0]["intent"]["entity"] == "проект"

    def test_window_limit(self):
        memory = ContextMemory(window=3)
        for i in range(5):
            memory.remember("s1", {"action": "create", "entity": f"e{i}"})
        entries = memory.get("s1")
        assert len(entries) == 3
        assert entries[-1]["intent"]["entity"] == "e4"

    def test_sessions_isolated(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "a"})
        memory.remember("s2", {"action": "create", "entity": "b"})
        assert memory.get("s1")[0]["intent"]["entity"] == "a"
        assert memory.get("s2")[0]["intent"]["entity"] == "b"

    def test_unknown_session_empty(self, memory: ContextMemory):
        assert memory.get("missing") == []


class TestReferenceResolution:
    def test_resolve_after_create(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "Проект"})
        resolved = memory.resolve("s1", {"action": "delete", "entity": "его"})
        # Имя подставляется как сохранено — регистр сохраняется
        assert resolved["entity"] == "Проект"
        assert resolved["resolved_references"] == ["Проект"]

    def test_resolve_after_link_uses_last_entity(self, memory: ContextMemory):
        memory.remember("s1", {"action": "link", "entities": ["дом", "огород"]})
        resolved = memory.resolve("s1", {"action": "query", "entity": "это"})
        assert resolved["entity"] == "огород"

    def test_resolve_in_entities_list(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "проект"})
        resolved = memory.resolve(
            "s1", {"action": "link", "entities": ["он", "задача"]}
        )
        assert resolved["entities"] == ["проект", "задача"]

    def test_unresolved_reference(self, memory: ContextMemory):
        resolved = memory.resolve("empty-session", {"action": "delete", "entity": "он"})
        assert resolved["unresolved_reference"] == "он"
        assert resolved["entity"] == "он"

    def test_real_names_not_replaced(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "проект"})
        resolved = memory.resolve("s1", {"action": "delete", "entity": "грядка"})
        assert resolved["entity"] == "грядка"


class TestTTL:
    def test_expired_entries_filtered(self):
        memory = ContextMemory(ttl=100)
        memory.remember("s1", {"action": "create", "entity": "a"}, ts=1000)
        memory.remember("s1", {"action": "create", "entity": "b"}, ts=1050)
        # now=1100: запись a (1000+100=1100 не > 1100) истекла, b жива
        entries = memory.get("s1")
        assert len(entries) == 0 or entries[-1]["intent"]["entity"] == "b"

    def test_ttl_5_minutes_default(self):
        memory = ContextMemory()
        assert memory.ttl == 300

    def test_context_clears_after_inactivity(self):
        memory = ContextMemory(ttl=300)
        memory.remember("s1", {"action": "create", "entity": "a"}, ts=1000)
        # Спустя 301 секунду неактивности контекст пуст
        assert memory.get("s1") == []
        assert memory.last_entity("s1") is None

    def test_two_requests_connected(self, memory: ContextMemory):
        memory.remember("s1", {"action": "create", "entity": "Проект"})
        first = memory.resolve("s1", {"action": "query", "entity": "проект"})
        second = memory.resolve("s1", {"action": "delete", "entity": "это"})
        assert first["entity"] == "проект"
        assert second["entity"] == "Проект"


class TestBackends:
    def test_file_backend_roundtrip(self, tmp_path: Path):
        backend = FileBackend(tmp_path / "ctx")
        memory = ContextMemory(backend=backend)
        memory.remember("s1", {"action": "create", "entity": "проект"})
        # Новый экземпляр с тем же backend видит данные
        memory2 = ContextMemory(backend=backend)
        assert memory2.last_entity("s1") == "проект"

    def test_file_backend_special_chars_in_session_id(self, tmp_path: Path):
        backend = FileBackend(tmp_path / "ctx")
        memory = ContextMemory(backend=backend)
        memory.remember("session/with:chars", {"action": "create", "entity": "x"})
        assert memory.get("session/with:chars")[0]["intent"]["entity"] == "x"

    def test_redis_backend_with_fake_client(self):
        class FakeRedis:
            def __init__(self):
                self.store = {}

            def set(self, key, value, ex=None):
                self.store[key] = value

            def setex(self, key, ttl, value):
                self.store[key] = value

            def get(self, key):
                return self.store.get(key)

            def delete(self, key):
                self.store.pop(key, None)

        client = FakeRedis()
        backend = RedisBackend(client)
        memory = ContextMemory(backend=backend)
        memory.remember("s1", {"action": "create", "entity": "проект"})
        memory2 = ContextMemory(backend=RedisBackend(client))
        assert memory2.last_entity("s1") == "проект"
        memory2.clear("s1")
        assert memory2.get("s1") == []


class TestSerialization:
    def test_export_import(self, tmp_path: Path):
        backend = FileBackend(tmp_path / "ctx")
        memory = ContextMemory(backend=backend)
        memory.remember("s1", {"action": "create", "entity": "проект"})
        exported = memory.export("s1")
        assert exported["session_id"] == "s1"
        other = ContextMemory()
        other.import_("s2", exported)
        assert other.last_entity("s2") == "проект"

    def test_import_rejects_bad_data(self):
        memory = ContextMemory()
        with pytest.raises(ValueError):
            memory.import_("s1", {"entries": "not-a-list"})

    def test_clear_requires_session(self):
        memory = ContextMemory()
        with pytest.raises(ValueError):
            memory.clear()
