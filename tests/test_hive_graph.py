"""
Issues #13/#14 (hive): иерархия и типизированные связи в in-memory графе.
"""

from __future__ import annotations

import pytest

from core.symbio_hive import hive
from core.symbio_hive.links import LinkType, is_cycle_checked, normalize_link_type


@pytest.fixture(autouse=True)
def clean_hive():
    hive.reset()
    yield
    hive.reset()


class TestHierarchy:
    def test_create_with_parent(self):
        parent = hive.create_entity("Дом")
        child = hive.create_entity("Комната", parent_id=parent["id"])
        assert child["parent_id"] == parent["id"]

    def test_create_with_missing_parent_raises(self):
        with pytest.raises(ValueError):
            hive.create_entity("Сирота", parent_id=999)

    def test_children_and_has_children(self):
        parent = hive.create_entity("Дом")
        hive.create_entity("Комната", parent_id=parent["id"])
        assert hive.has_children("Дом")
        assert not hive.has_children("Комната")
        children = hive.get_children("Дом")
        assert [c["name"] for c in children] == ["Комната"]

    def test_subtree(self):
        root = hive.create_entity("Дом")
        floor = hive.create_entity("Этаж", parent_id=root["id"])
        hive.create_entity("Комната", parent_id=floor["id"])
        tree = hive.get_subtree("Дом")
        assert tree["name"] == "Дом"
        assert tree["children"][0]["name"] == "Этаж"
        assert tree["children"][0]["children"][0]["name"] == "Комната"

    def test_subtree_depth_limit(self):
        root = hive.create_entity("A")
        mid = hive.create_entity("B", parent_id=root["id"])
        hive.create_entity("C", parent_id=mid["id"])
        tree = hive.get_subtree("A", max_depth=1)
        assert tree["children"][0]["name"] == "B"
        assert tree["children"][0]["children"] == []

    def test_subtree_missing_root(self):
        assert hive.get_subtree("нет") is None

    def test_set_parent_rejects_cycle(self):
        a = hive.create_entity("A")
        b = hive.create_entity("B")
        assert hive.set_parent("B", "A")
        assert not hive.set_parent("A", "B")  # A → B → A цикл
        assert not hive.set_parent("A", "A")

    def test_delete_parent_detaches_children(self):
        parent = hive.create_entity("Дом")
        child = hive.create_entity("Комната", parent_id=parent["id"])
        hive.delete_entity("Дом")
        entities = {e["name"].lower(): e for e in hive.get_entities()}
        assert entities["комната"]["parent_id"] is None


class TestTypedLinks:
    def test_default_type_is_relates(self):
        hive.create_entity("A")
        hive.create_entity("B")
        link = hive.link_entities("A", "B")
        assert link["type"] == "relates"

    def test_all_five_types(self):
        for name in ("A", "B", "C"):
            hive.create_entity(name)
        hive.link_entities("A", "B", "contains")
        hive.link_entities("B", "C", "depends")
        hive.link_entities("C", "A", "blocks")
        hive.link_entities("A", "C", "triggers")
        assert len(hive.get_links()) == 4
        assert hive.link_type_distribution()["depends"] == 1

    def test_filter_by_type(self):
        hive.create_entity("A")
        hive.create_entity("B")
        hive.link_entities("A", "B", "depends")
        hive.link_entities("A", "B", "relates")
        depends = hive.get_links("depends")
        assert len(depends) == 1
        assert depends[0]["type"] == "depends"

    def test_duplicate_same_type_not_added(self):
        hive.create_entity("A")
        hive.create_entity("B")
        first = hive.link_entities("A", "B", "depends")
        second = hive.link_entities("A", "B", "depends")
        assert first["id"] == second["id"]
        assert len(hive.get_links()) == 1

    def test_same_pair_different_types_ok(self):
        hive.create_entity("A")
        hive.create_entity("B")
        hive.link_entities("A", "B", "depends")
        hive.link_entities("A", "B", "relates")
        assert len(hive.get_links()) == 2

    def test_missing_entities_returns_none(self):
        assert hive.link_entities("Нет", "Тоже нет") is None


class TestCycleDetection:
    def test_direct_cycle_rejected_for_depends(self):
        hive.create_entity("A")
        hive.create_entity("B")
        hive.link_entities("A", "B", "depends")
        # A → B уже есть; B → A создаст цикл
        assert hive.link_entities("B", "A", "depends") is None

    def test_transitive_cycle_rejected_for_blocks(self):
        for name in ("A", "B", "C"):
            hive.create_entity(name)
        hive.link_entities("A", "B", "blocks")
        hive.link_entities("B", "C", "blocks")
        # C → A создаст транзитивный цикл
        assert hive.link_entities("C", "A", "blocks") is None

    def test_relates_allows_any_direction(self):
        hive.create_entity("A")
        hive.create_entity("B")
        hive.link_entities("A", "B", "relates")
        assert hive.link_entities("B", "A", "relates") is not None

    def test_creates_cycle_function(self):
        a = hive.create_entity("A")
        b = hive.create_entity("B")
        hive.link_entities("A", "B", "depends")
        assert hive.creates_cycle(a["id"], b["id"], "depends") is False
        assert hive.creates_cycle(b["id"], a["id"], "depends") is True


class TestLinkTypeHelpers:
    def test_values(self):
        assert LinkType.values() == ("contains", "depends", "relates", "blocks", "triggers")

    def test_normalize(self):
        assert normalize_link_type(None) == "relates"
        assert normalize_link_type("DEPENDS") == "depends"
        assert normalize_link_type("bogus") == "relates"
        assert normalize_link_type(LinkType.BLOCKS) == "blocks"

    def test_cycle_checked(self):
        assert is_cycle_checked("depends")
        assert is_cycle_checked("blocks")
        assert not is_cycle_checked("relates")
        assert not is_cycle_checked("contains")
        assert not is_cycle_checked("triggers")
