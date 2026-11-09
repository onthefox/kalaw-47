"""
API-тесты: все эндпоинты FastAPI (issues #9–#17, #20) через TestClient.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


class TestHealthAndStats:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "Adapt SymbioSystem"}

    def test_stats_structure(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("entities", "links", "links_by_type", "root_entities", "events"):
            assert key in data


class TestIntentEndpoint:
    def test_create_via_intent(self, client):
        resp = client.post(
            "/intent", json={"intent": "создать стол", "session_id": "api-1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "create"
        assert "confidence" in data and "route" in data
        assert "intent_id" in data

    def test_empty_intent_rejected(self, client):
        resp = client.post("/intent", json={"intent": "   "})
        assert resp.status_code == 400

    def test_pronoun_resolution_across_requests(self, client):
        client.post("/intent", json={"intent": "создать стул", "session_id": "api-2"})
        resp = client.post(
            "/intent", json={"intent": "удалить его", "session_id": "api-2"}
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "delete"
        assert resp.json()["deleted"] == "стул"

    def test_feedback_endpoint(self, client):
        resp = client.post(
            "/intent/feedback",
            json={"intent_id": "abc123", "action": "create", "accepted": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recorded"] is True
        assert data["stats"]["total"] == 1


class TestEntitiesHierarchy:
    def test_create_entity_with_parent(self, client):
        parent = client.post("/entity", json={"name": "Дом"}).json()["created"]
        child = client.post(
            "/entity", json={"name": "Комната", "parent_id": parent["id"]}
        ).json()["created"]
        assert child["parent_id"] == parent["id"]
        assert child["has_children"] is False
        # has_children в ответе на создание — снимок до добавления ребёнка;
        # перепроверяем актуальное состояние через список.
        fetched = {i["name"]: i for i in client.get("/entities").json()["items"]}
        assert fetched["Дом"]["has_children"] is True
        assert fetched["Комната"]["has_children"] is False

    def test_create_entity_empty_name_rejected(self, client):
        resp = client.post("/entity", json={"name": "  "})
        assert resp.status_code == 400

    def test_create_entity_existing_returns_exists(self, client):
        first = client.post("/entity", json={"name": "X"})
        second = client.post("/entity", json={"name": "X"})
        assert first.json()["created"]["name"] == "X"
        assert second.json()["exists"]["name"] == "X"

    def test_create_entity_unknown_parent_404(self, client):
        resp = client.post("/entity", json={"name": "Сирота", "parent_id": 9999})
        assert resp.status_code == 404

    def test_list_entities_flat(self, client):
        client.post("/entity", json={"name": "А"})
        client.post("/entity", json={"name": "Б"})
        data = client.get("/entities").json()
        assert data["total"] >= 2
        names = {item["name"] for item in data["items"]}
        assert {"А", "Б"} <= names
        assert all("parent_id" in item for item in data["items"])

    def test_list_entities_tree(self, client):
        parent = client.post("/entity", json={"name": "Корень"}).json()["created"]
        client.post("/entity", json={"name": "Лист", "parent_id": parent["id"]})
        data = client.get("/entities", params={"tree": "true"}).json()
        assert data["mode"] == "tree"
        root = next(n for n in data["items"] if n["name"] == "Корень")
        assert root["children"][0]["name"] == "Лист"

    def test_tree_with_root_and_depth(self, client):
        root = client.post("/entity", json={"name": "T-корень"}).json()["created"]
        mid = client.post(
            "/entity", json={"name": "T-середина", "parent_id": root["id"]}
        ).json()["created"]
        client.post("/entity", json={"name": "T-лист", "parent_id": mid["id"]})
        data = client.get(
            "/entities",
            params={"tree": "true", "root_id": root["id"], "max_depth": 1},
        ).json()
        node = data["items"][0]
        assert node["name"] == "T-корень"
        assert node["children"][0]["name"] == "T-середина"
        assert node["children"][0]["children"] == []

    def test_tree_unknown_root_404(self, client):
        resp = client.get("/entities", params={"tree": "true", "root_id": 424242})
        assert resp.status_code == 404

    def test_descendants_endpoint(self, client):
        root = client.post("/entity", json={"name": "D-корень"}).json()["created"]
        mid = client.post(
            "/entity", json={"name": "D-середина", "parent_id": root["id"]}
        ).json()["created"]
        client.post("/entity", json={"name": "D-лист", "parent_id": mid["id"]})
        data = client.get(f"/entities/{root['id']}/descendants").json()
        assert data["count"] == 2
        limited = client.get(
            f"/entities/{root['id']}/descendants", params={"max_depth": 1}
        ).json()
        assert limited["count"] == 1

    def test_set_parent_and_cycle_rejected(self, client):
        a = client.post("/entity", json={"name": "PA"}).json()["created"]
        b = client.post("/entity", json={"name": "PB"}).json()["created"]
        client.post(f"/entity/{b['id']}/parent", params={"parent_id": a["id"]})
        # a → b → a цикл
        resp = client.post(f"/entity/{a['id']}/parent", params={"parent_id": b["id"]})
        assert resp.status_code == 400
        self_resp = client.post(f"/entity/{a['id']}/parent", params={"parent_id": a["id"]})
        assert self_resp.status_code == 400
        detach = client.post(f"/entity/{b['id']}/parent")
        assert detach.json()["updated"]["parent_id"] is None


class TestLinks:
    def test_create_link_relates(self, client):
        client.post("/entity", json={"name": "L1"})
        client.post("/entity", json={"name": "L2"})
        resp = client.post(
            "/link", json={"source": "L1", "target": "L2", "type": "relates"}
        )
        assert resp.status_code == 200
        assert resp.json()["created"]["type"] == "relates"

    def test_link_self_rejected(self, client):
        client.post("/entity", json={"name": "Solo"})
        resp = client.post("/link", json={"source": "Solo", "target": "Solo"})
        assert resp.status_code == 400

    def test_link_unknown_entity_404(self, client):
        resp = client.post("/link", json={"source": "Нет", "target": "Тоже нет"})
        assert resp.status_code == 404

    def test_link_invalid_type_400(self, client):
        client.post("/entity", json={"name": "V1"})
        client.post("/entity", json={"name": "V2"})
        resp = client.post("/link", json={"source": "V1", "target": "V2", "type": "chicken"})
        assert resp.status_code == 400

    def test_depends_cycle_rejected(self, client):
        client.post("/entity", json={"name": "C1"})
        client.post("/entity", json={"name": "C2"})
        first = client.post("/link", json={"source": "C1", "target": "C2", "type": "depends"})
        assert first.status_code == 200
        back = client.post("/link", json={"source": "C2", "target": "C1", "type": "depends"})
        assert back.status_code == 400

    def test_list_links_filter_by_type(self, client):
        client.post("/entity", json={"name": "F1"})
        client.post("/entity", json={"name": "F2"})
        client.post("/link", json={"source": "F1", "target": "F2", "type": "depends"})
        client.post("/link", json={"source": "F1", "target": "F2", "type": "triggers"})
        data = client.get("/links", params={"type": "depends"}).json()
        assert data["total"] == 1
        assert data["items"][0]["type"] == "depends"
        all_links = client.get("/links").json()
        assert all_links["total"] == 2

    def test_list_links_invalid_type_400(self, client):
        resp = client.get("/links", params={"type": "chicken"})
        assert resp.status_code == 400


class TestOntologyEndpoints:
    def test_export_json(self, client):
        client.post("/entity", json={"name": "O1"})
        data = client.get("/ontology/export").json()
        assert data["version"] == 1
        assert any(e["name"] == "O1" for e in data["entities"])

    def test_export_graphml(self, client):
        a = client.post("/entity", json={"name": "G1"}).json()["created"]
        b = client.post("/entity", json={"name": "G2"}).json()["created"]
        client.post("/link", json={"source": "G1", "target": "G2", "type": "depends"})
        resp = client.get("/ontology/export", params={"format": "graphml"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        root = ET.fromstring(resp.text)
        graph = root.find("{http://graphml.graphdrawing.org/xmlns}graph")
        assert graph is not None
        assert len(graph.findall("{http://graphml.graphdrawing.org/xmlns}node")) == 2
        assert len(graph.findall("{http://graphml.graphdrawing.org/xmlns}edge")) == 1

    def test_import_merge(self, client):
        payload = {
            "entities": [{"id": 1, "name": "Имп1"}, {"id": 2, "name": "Имп2"}],
            "links": [{"source_id": 1, "target_id": 2, "type": "contains"}],
        }
        resp = client.post("/ontology/import", params={"mode": "merge"}, json=payload)
        assert resp.status_code == 200
        stats = resp.json()["imported"]
        assert stats["entities_created"] == 2
        assert stats["links_created"] == 1

    def test_import_invalid_payload_400(self, client):
        resp = client.post(
            "/ontology/import", json={"entities": [{"id": 1}]}  # без name
        )
        assert resp.status_code == 400

    def test_import_replace(self, client):
        payload = {"entities": [{"id": 5, "name": "R1"}], "links": []}
        resp = client.post("/ontology/import", params={"mode": "replace"}, json=payload)
        assert resp.status_code == 200
        data = client.get("/entities").json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "R1"

    def test_roundtrip_export_then_import(self, client):
        client.post("/entity", json={"name": "RT1"})
        client.post("/entity", json={"name": "RT2"})
        client.post("/link", json={"source": "RT1", "target": "RT2", "type": "relates"})
        exported = client.get("/ontology/export").json()
        client.post("/ontology/import", params={"mode": "replace"}, json=exported)
        names = {i["name"] for i in client.get("/entities").json()["items"]}
        assert names == {"RT1", "RT2"}


class TestObserverEndpoints:
    def test_events_after_entity_creation(self, client):
        client.post("/entity", json={"name": "EV1"})
        data = client.get("/events", params={"event_type": "entity.created"}).json()
        assert any(i["entity"] == "EV1" for i in data["items"])

    def test_events_entity_filter(self, client):
        client.post("/entity", json={"name": "EVX"})
        client.post("/entity", json={"name": "EVY"})
        data = client.get("/events", params={"entity": "EVX"}).json()
        assert data["items"]
        assert all(i["entity"] == "EVX" for i in data["items"])

    def test_alert_rules_and_alerts(self, client):
        resp = client.post(
            "/alerts/rules",
            params={"pattern": "entity.created", "threshold": 2, "window": 60},
        )
        assert resp.status_code == 200
        assert len(resp.json()["rules"]) == 1
        client.post("/entity", json={"name": "AL1"})
        assert client.get("/alerts").json()["items"] == []
        client.post("/entity", json={"name": "AL2"})
        alerts = client.get("/alerts").json()["items"]
        assert len(alerts) == 1
        assert alerts[0]["pattern"] == "entity.created"


class TestPlannerEndpoints:
    def test_plan_valid(self, client):
        resp = client.post(
            "/plan",
            json={"intents": ["создать план1", "создать план2", "связать план1 и план2"], "goal": "g"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["plan"]["goal"] == "g"
        assert len(data["plan"]["steps"]) == 3

    def test_plan_invalid(self, client):
        resp = client.post("/plan", json={"intents": ["левой ногой вправо"]})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_plan_execute(self, client):
        resp = client.post(
            "/plan/execute",
            json={"intents": ["создать ex1", "создать ex2", "связать ex1 и ex2"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        names = {i["name"] for i in client.get("/entities").json()["items"]}
        assert {"ex1", "ex2"} <= names

    def test_plan_execute_invalid_400(self, client):
        resp = client.post("/plan/execute", json={"intents": ["тарабарщина скуф"]})
        assert resp.status_code == 400


class TestAutogenEndpoints:
    def test_templates_list(self, client):
        data = client.get("/autogen/templates").json()
        assert len(data["templates"]) == 5
        assert "python_module" in data["templates"]

    def test_generate_module(self, client):
        resp = client.post(
            "/autogen",
            json={"template": "python_module", "name": "ApiModule", "type": "service"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["elapsed_ms"] < 5000
        assert data["entity"]["name"] == "ApiModule"

    def test_generate_module_unknown_template_400(self, client):
        resp = client.post("/autogen", json={"template": "nope", "name": "X"})
        assert resp.status_code == 400

    def test_generated_module_registered_in_entities(self, client):
        client.post("/autogen", json={"template": "docs", "name": "DocMod"})
        names = {i["name"] for i in client.get("/entities").json()["items"]}
        assert "DocMod" in names


class TestLLMStatus:
    def test_llm_status_structure(self, client):
        data = client.get("/llm/status").json()
        assert "available" in data
        assert "providers" in data
        assert "rate_limit" in data
        assert "cost" in data
        assert {p["name"] for p in data["providers"]} == {"openai", "anthropic", "google"}
