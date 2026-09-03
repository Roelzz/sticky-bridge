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


def test_stream_ask_parses_sse_and_truncates(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        b': keepalive\n\n',
        b'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" wereld"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]

    class FakeResponse:
        def __iter__(self):
            return iter(lines)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = HermesClient("http://h.test", "k", "m")
    monkeypatch.setattr(client, "_open_stream", lambda q: FakeResponse())
    assert "".join(client.stream_ask("q", 240)) == "Hallo wereld"

    client2 = HermesClient("http://h.test", "k", "m")
    monkeypatch.setattr(client2, "_open_stream", lambda q: FakeResponse())
    assert "".join(client2.stream_ask("q", 7)) == "Hallo w"


def test_chat_streams_plain_text_when_accepted(token_secret, hermes_key,
                                               monkeypatch):
    monkeypatch.setattr(
        HermesClient, "stream_ask",
        lambda self, q, m: iter(["Hete", " dag"]),
    )
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hai"},
        headers={"X-Bridge-Token": TEST_TOKEN, "Accept": "text/plain"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hete dag"


def test_chat_stream_falls_back_to_runs_api(token_secret, hermes_key,
                                            monkeypatch):
    def broken_stream(self, q, m):
        raise HermesError("no stream")
        yield ""

    async def fake_ask(self, question, max_answer_chars):
        return "fallback antwoord"

    monkeypatch.setattr(HermesClient, "stream_ask", broken_stream)
    monkeypatch.setattr(HermesClient, "ask", fake_ask)
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hai"},
        headers={"X-Bridge-Token": TEST_TOKEN, "Accept": "text/plain"},
    )
    assert response.status_code == 200
    assert response.text == "fallback antwoord"


def test_chat_stream_without_accept_still_json(token_secret, hermes_key,
                                               monkeypatch):
    async def fake_ask(self, question, max_answer_chars):
        return "json antwoord"

    monkeypatch.setattr(HermesClient, "ask", fake_ask)
    response = TestClient(main.app).post(
        "/api/chat", json={"question": "hai"},
        headers={"X-Bridge-Token": TEST_TOKEN},
    )
    assert response.json() == {"answer": "json antwoord"}


def test_stream_with_keepalive_emits_on_silence():
    import time

    def slow_stream():
        time.sleep(0.05)
        yield "A"

    async def collect():
        pieces = []
        async for piece in main._stream_with_keepalive(slow_stream(),
                                                       interval=0.01):
            pieces.append(piece)
        return pieces

    import asyncio

    pieces = asyncio.run(collect())
    assert pieces[-1] == "A"
    assert "\r" in pieces
