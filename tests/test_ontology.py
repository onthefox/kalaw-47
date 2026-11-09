"""
Issue #15: экспорт/импорт онтологии — JSON, GraphML, валидация, replace/merge.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from backend.models import Entity, Link
from backend.ontology import (
    GRAPHML_NS,
    apply_import,
    export_graphml,
    export_json,
    parse_import_payload,
    validate_payload,
)
from engine.observer import observer


@pytest.fixture()
def populated(db_session):
    a = Entity(id=1, name="А", meta='{"x": 1}')
    b = Entity(id=2, name="Б", meta="{}")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(Link(source_id=1, target_id=2, type="depends", meta="{}"))
    db_session.commit()
    return db_session


class TestExport:
    def test_export_json_structure(self, populated):
        data = export_json(populated)
        assert data["version"] == 1
        names = {e["name"] for e in data["entities"]}
        assert names == {"А", "Б"}
        assert data["entities"][0]["parent_id"] is None
        assert data["entities"][0]["has_children"] is False

    def test_export_json_links_have_type(self, populated):
        data = export_json(populated)
        assert len(data["links"]) == 1
        assert data["links"][0]["type"] == "depends"

    def test_export_json_roundtrip_meta(self, populated):
        data = export_json(populated)
        a = next(e for e in data["entities"] if e["name"] == "А")
        assert json.loads(a["meta"]) == {"x": 1}

    def test_export_graphml_is_parseable_xml(self, populated):
        xml = export_graphml(populated)
        root = ET.fromstring(xml)
        assert root.tag == f"{{{GRAPHML_NS}}}graphml"
        graph = root.find(f"{{{GRAPHML_NS}}}graph")
        assert graph is not None
        assert graph.get("edgedefault") == "directed"

    def test_export_graphml_nodes_and_edges(self, populated):
        xml = export_graphml(populated)
        root = ET.fromstring(xml)
        graph = root.find(f"{{{GRAPHML_NS}}}graph")
        node_ids = {n.get("id") for n in graph.findall(f"{{{GRAPHML_NS}}}node")}
        assert node_ids == {"n1", "n2"}
        edges = graph.findall(f"{{{GRAPHML_NS}}}edge")
        assert len(edges) == 1
        assert edges[0].get("source") == "n1"
        assert edges[0].get("target") == "n2"
        edge_type = edges[0].find(f"{{{GRAPHML_NS}}}data[@key='d_type']")
        assert edge_type.text == "depends"

    def test_graphml_roundtrip_through_import(self, populated):
        xml = export_graphml(populated)
        payload = parse_import_payload(xml)
        assert {e["name"] for e in payload["entities"]} == {"А", "Б"}
        assert payload["links"][0]["type"] == "depends"


class TestValidatePayload:
    def test_valid_payload_no_errors(self):
        clean, errors = validate_payload(
            {
                "entities": [{"id": 1, "name": "А"}, {"id": 2, "name": "Б"}],
                "links": [{"source_id": 1, "target_id": 2, "type": "depends"}],
            }
        )
        assert errors == []
        assert len(clean["entities"]) == 2
        assert clean["links"][0]["type"] == "depends"

    def test_non_dict_payload(self):
        clean, errors = validate_payload([1, 2, 3])
        assert errors == ["payload должен быть объектом"]
        assert clean == {"entities": [], "links": []}

    def test_entities_not_list(self):
        clean, errors = validate_payload({"entities": "нет"})
        assert "entities должен быть списком" in errors
        assert clean["entities"] == []

    def test_missing_name_rejected(self):
        clean, errors = validate_payload({"entities": [{"id": 1}]})
        assert any("отсутствует name" in e for e in errors)
        assert clean["entities"] == []

    def test_duplicate_name_rejected(self):
        clean, errors = validate_payload(
            {"entities": [{"id": 1, "name": "А"}, {"id": 2, "name": "а"}]}
        )
        assert any("дубликат имени" in e for e in errors)
        assert len(clean["entities"]) == 1

    def test_duplicate_id_rejected(self):
        clean, errors = validate_payload(
            {"entities": [{"id": 1, "name": "А"}, {"id": 1, "name": "Б"}]}
        )
        assert any("дубликат id" in e for e in errors)
        assert len(clean["entities"]) == 1

    def test_bad_id_rejected(self):
        clean, errors = validate_payload({"entities": [{"id": -5, "name": "А"}]})
        assert any("некорректный id" in e for e in errors)
        assert clean["entities"] == []

    def test_meta_dict_normalized_to_string(self):
        clean, _ = validate_payload({"entities": [{"id": 1, "name": "А", "meta": {"x": 2}}]})
        assert clean["entities"][0]["meta"] == json.dumps({"x": 2}, ensure_ascii=False)

    def test_link_endpoint_missing(self):
        clean, errors = validate_payload(
            {"entities": [{"id": 1, "name": "А"}], "links": [{"source_id": 1, "target_id": 9}]}
        )
        assert any("не найдены в entities" in e for e in errors)
        assert clean["links"] == []

    def test_link_bad_ids(self):
        clean, errors = validate_payload(
            {"entities": [{"id": 1, "name": "А"}], "links": [{"source_id": "x", "target_id": None}]}
        )
        assert any("некорректные source_id/target_id" in e for e in errors)
        assert clean["links"] == []

    def test_link_unknown_type_normalized(self):
        clean, errors = validate_payload(
            {
                "entities": [{"id": 1, "name": "А"}, {"id": 2, "name": "Б"}],
                "links": [{"source_id": 1, "target_id": 2, "type": "chicken"}],
            }
        )
        assert errors == []
        assert clean["links"][0]["type"] == "relates"


class TestParseImportPayload:
    def test_dict_with_entities_passthrough(self):
        payload = {"entities": [{"id": 1, "name": "А"}], "links": []}
        assert parse_import_payload(payload) is payload

    def test_data_wrapper_with_json_string(self):
        inner = json.dumps({"entities": [{"id": 1, "name": "А"}]})
        result = parse_import_payload({"data": inner})
        assert result["entities"][0]["name"] == "А"

    def test_data_wrapper_with_dict(self):
        inner = {"entities": [{"id": 1, "name": "А"}]}
        assert parse_import_payload({"data": inner}) is inner

    def test_json_string(self):
        result = parse_import_payload('{"entities": [{"id": 1, "name": "А"}]}')
        assert result["entities"][0]["id"] == 1

    def test_xml_string(self, populated):
        result = parse_import_payload(export_graphml(populated))
        assert len(result["entities"]) == 2

    def test_invalid_dict_raises(self):
        with pytest.raises(ValueError):
            parse_import_payload({"format": "graphml"})

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError):
            parse_import_payload(42)

    def test_invalid_xml_raises(self):
        with pytest.raises(ValueError):
            parse_import_payload("<not-xml")

    def test_graphml_without_graph_raises(self):
        with pytest.raises(ValueError):
            parse_import_payload(
                f'<graphml xmlns="{GRAPHML_NS}"></graphml>'
            )


class TestApplyImport:
    def test_merge_creates_new_entities(self, db_session):
        data = validate_payload(
            {"entities": [{"id": 1, "name": "А"}, {"id": 2, "name": "Б"}]}
        )[0]
        stats = apply_import(db_session, data, mode="merge")
        assert stats["entities_created"] == 2
        assert stats["entities_skipped"] == 0
        names = {e.name for e in db_session.query(Entity).all()}
        assert names == {"А", "Б"}

    def test_merge_skips_existing_by_name(self, populated):
        data = validate_payload(
            {
                "entities": [{"id": 1, "name": "А"}, {"id": 3, "name": "В"}],
                "links": [{"source_id": 1, "target_id": 3, "type": "relates"}],
            }
        )[0]
        stats = apply_import(populated, data, mode="merge")
        assert stats["entities_created"] == 1
        assert stats["entities_skipped"] == 1
        names = {e.name for e in populated.query(Entity).all()}
        assert names == {"А", "Б", "В"}

    def test_merge_skips_duplicate_links(self, populated):
        data = validate_payload(
            {
                "entities": [{"id": 1, "name": "А"}, {"id": 2, "name": "Б"}],
                "links": [{"source_id": 1, "target_id": 2, "type": "depends"}],
            }
        )[0]
        stats = apply_import(populated, data, mode="merge")
        assert stats["links_created"] == 0
        assert stats["links_skipped"] == 1

    def test_replace_wipes_and_preserves_ids(self, populated):
        data = validate_payload(
            {
                "entities": [{"id": 10, "name": "X"}, {"id": 20, "name": "Y"}],
                "links": [{"source_id": 10, "target_id": 20, "type": "contains"}],
            }
        )[0]
        stats = apply_import(populated, data, mode="replace")
        assert stats["mode"] == "replace"
        assert stats["entities_created"] == 2
        entities = {e.id: e.name for e in populated.query(Entity).all()}
        assert entities == {10: "X", 20: "Y"}
        link = populated.query(Link).one()
        assert (link.source_id, link.target_id, link.type) == (10, 20, "contains")

    def test_replace_parent_assignment_second_pass(self, populated):
        data = validate_payload(
            {
                "entities": [
                    {"id": 10, "name": "X"},
                    {"id": 11, "name": "Y", "parent_id": 10},
                ],
            }
        )[0]
        apply_import(populated, data, mode="replace")
        y = populated.query(Entity).filter_by(name="Y").one()
        x = populated.query(Entity).filter_by(name="X").one()
        assert y.parent_id == x.id

    def test_invalid_mode_raises(self, db_session):
        with pytest.raises(ValueError):
            apply_import(db_session, {"entities": [], "links": []}, mode="upsert")

    def test_publishes_ontology_imported_event(self, db_session):
        data = validate_payload({"entities": [{"id": 1, "name": "А"}]})[0]
        apply_import(db_session, data, mode="merge")
        entries = observer.get_log(event_type="ontology.imported")
        assert len(entries) == 1
