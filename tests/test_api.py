"""Endpoint behaviour + failure modes via FastAPI TestClient.

None of these make real OpenAI/Pinecone calls: the deterministic endpoints need
no keys, and the /analyze cases hit the config guard, a 400, or a monkeypatched
agent — so the suite is fast and free."""
import pytest
from fastapi.testclient import TestClient

import src.api as api


@pytest.fixture
def client():
    return TestClient(api.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_check_grounded_pair(client):
    r = client.post("/check", json={"drugs": ["azilsartan", "fluconazole"]})
    assert r.status_code == 200
    assert r.json()["interactions"][0]["evidence"]["type"] != "missing_drug"


def test_check_refuses_unknown_drug(client):
    r = client.post("/check", json={"drugs": ["warfarin", "azilsartan"]})
    assert r.status_code == 200
    assert r.json()["interactions"][0]["evidence"]["type"] == "missing_drug"


def test_check_needs_two_drugs(client):
    assert client.post("/check", json={"drugs": ["azilsartan"]}).status_code == 400


def test_check_empty_input(client):
    assert client.post("/check", json={"drugs": []}).status_code == 400
    # whitespace-only names are filtered out, then rejected
    assert client.post("/check", json={"drugs": [" ", ""]}).status_code == 400


def test_drug_lookup_found(client):
    assert client.get("/drug/azilsartan").status_code == 200


def test_drug_lookup_404(client, monkeypatch):
    # stub RxNorm so the miss path doesn't hit the network
    from src.services import rxnorm
    monkeypatch.setattr(rxnorm, "resolve", lambda n: rxnorm.RxNormMatch(n, "unresolved"))
    assert client.get("/drug/asdfghjkl").status_code == 404


def test_analyze_empty_input(client):
    assert client.post("/analyze", json={"drugs": []}).status_code == 400


def test_analyze_unconfigured_returns_503(client, monkeypatch):
    # failure mode: keys missing -> graceful 503, not a crash
    monkeypatch.setattr(api, "OPENAI_API_KEY", "")
    r = client.post("/analyze", json={"drugs": ["azilsartan"]})
    assert r.status_code == 503


def test_analyze_backend_timeout_surfaces_5xx(monkeypatch):
    # failure mode: an upstream timeout currently surfaces as a 500.
    # (Graceful timeout handling is a known gap — this test documents behaviour.)
    def boom():
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr(api, "get_agent", boom)
    client = TestClient(api.app, raise_server_exceptions=False)
    r = client.post("/analyze", json={"drugs": ["azilsartan"]})
    assert r.status_code == 500
