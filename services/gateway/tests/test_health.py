from fastapi.testclient import TestClient

from services.gateway.main import app

client = TestClient(app)


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz() -> None:
    assert client.get("/readyz").json()["status"] == "ready"


def test_request_id_echoed() -> None:
    r = client.get("/healthz", headers={"x-request-id": "test-123"})
    assert r.headers["x-request-id"] == "test-123"
