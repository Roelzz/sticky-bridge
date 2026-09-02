import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import main

TEST_TOKEN = "test-token-abc"


@pytest.fixture()
def token_secret(monkeypatch):
    monkeypatch.setattr(main.settings, "bridge_token", TEST_TOKEN)


def test_health_ok():
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "sticky-bridge",
        "version": main.VERSION,
    }


def _protected_client() -> TestClient:
    test_app = FastAPI()
    test_app.add_api_route(
        "/protected",
        lambda: {"ok": True},
        dependencies=[Depends(main.require_token)],
    )
    return TestClient(test_app)


def test_protected_rejects_missing_token(token_secret):
    response = _protected_client().get("/protected")
    assert response.status_code == 401


def test_protected_rejects_wrong_token(token_secret):
    response = _protected_client().get(
        "/protected", headers={"X-Bridge-Token": "wrong"}
    )
    assert response.status_code == 401


def test_protected_accepts_correct_token(token_secret):
    response = _protected_client().get(
        "/protected", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert response.status_code == 200


def test_protected_fails_closed_without_configured_token(monkeypatch):
    monkeypatch.setattr(main.settings, "bridge_token", "")
    response = _protected_client().get(
        "/protected", headers={"X-Bridge-Token": "anything"}
    )
    assert response.status_code == 503
