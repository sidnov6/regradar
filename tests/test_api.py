"""API tests with a deterministically-injected state (no network/LLM)."""
import pytest
from fastapi.testclient import TestClient

import regradar.server as server
from regradar.agents.impact.map import map_obligations
from regradar.agents.obligation.run import fold_into_state
from regradar.agents.prioritize.score import prioritize


@pytest.fixture
def client(groundtruth, bank_profile, parsed_dora):
    obls = [g.to_obligation() for g in groundtruth.obligations]
    links = map_obligations(obls, bank_profile)
    state = {"parsed_doc": parsed_dora, "obligations": obls, "impact_links": links,
             "prioritized": prioritize(obls, links), "audit_trail": [], "flags": [],
             "corpus_version": "cv:test", "status": "prioritizing"}
    server.svc._state = state
    server.svc._memo = None
    return TestClient(server.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_state_counters(client):
    d = client.get("/api/state").json()
    assert d["counters"]["obligations"] == 11
    assert d["counters"]["gaps"] == 3
    assert d["counters"]["coverage_pct"] == round(100 * 8 / 11)


def test_document_articles(client):
    d = client.get("/api/document").json()
    assert [a["number"] for a in d["articles"]] == ["5", "6", "17", "19", "24", "28"]


def test_memo_generate_and_approve(client):
    gen = client.post("/api/memo", json={"language": "en"}).json()
    assert gen["status"] == "draft" and gen["citations"] == 11
    appr = client.post("/api/memo/approve", json={"approver": "sid"}).json()
    assert appr["status"] == "approved" and appr["approver"] == "sid"


def test_memo_export_html(client):
    client.post("/api/memo", json={"language": "en"})
    r = client.get("/api/memo/export?format=html")
    assert r.status_code == 200 and "<table>" in r.text


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "RegRadar" in r.text
