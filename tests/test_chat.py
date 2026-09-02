import pytest
from fastapi.testclient import TestClient

import main
from hermes_client import HermesClient, HermesError

TEST_TOKEN = "test-token-abc"


@pytest.fixture()
def token_secret(monkeypatch):
    monkeypatch.setattr(main.settings, "bridge_token", TEST_TOKEN)


@pytest.fixture()
def hermes_key(monkeypatch):
    monkeypatch.setattr(main.settings, "hermes_api_key", "hkey")


def test_chat_rejects_missing_token(token_secret):
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hai"}
    )
    assert response.status_code == 401


def test_chat_fails_closed_without_hermes_key(token_secret):
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hai"},
        headers={"X-Bridge-Token": TEST_TOKEN},
    )
    assert response.status_code == 503


def test_chat_returns_answer(token_secret, hermes_key, monkeypatch):
    async def fake_ask(self, question, max_answer_chars):
        assert question == "hoe warm is het"
        return "18 graden"

    monkeypatch.setattr(HermesClient, "ask", fake_ask)
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hoe warm is het"},
        headers={"X-Bridge-Token": TEST_TOKEN},
    )
    assert response.status_code == 200
    assert response.json() == {"answer": "18 graden"}


def test_chat_rejects_empty_question(token_secret, hermes_key):
    response = TestClient(main.app).post(
        "/api/chat", json={"question": ""},
        headers={"X-Bridge-Token": TEST_TOKEN},
    )
    assert response.status_code == 422


def test_chat_bad_gateway_on_hermes_failure(token_secret, hermes_key,
                                            monkeypatch):
    async def broken_ask(self, question, max_answer_chars):
        raise HermesError("down")

    monkeypatch.setattr(HermesClient, "ask", broken_ask)
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "test"},
        headers={"X-Bridge-Token": TEST_TOKEN},
    )
    assert response.status_code == 502
