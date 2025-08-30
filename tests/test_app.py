from fastapi.testclient import TestClient

from src.app import app


client = TestClient(app)


def test_healthz_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_root_ok():
    resp = client.get("/")
    data = resp.json()
    assert resp.status_code == 200
    assert "service" in data and "version" in data


def test_update_log_level_ok():
    resp = client.post("/config/log-level", json={"level": "DEBUG"})
    assert resp.status_code == 200
    assert "log level set to" in resp.json()["message"].lower()


def test_update_log_level_invalid():
    resp = client.post("/config/log-level", json={"level": "NOPE"})
    assert resp.status_code == 400
    assert "invalid log level" in resp.json()["detail"].lower()
