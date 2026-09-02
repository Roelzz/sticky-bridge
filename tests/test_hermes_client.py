import asyncio
import json
from unittest import mock

import pytest

from hermes_client import HermesClient, HermesError


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_client() -> HermesClient:
    return HermesClient(
        "http://hermes.test", "key", "hermes-agent",
        overall_timeout=5.0, poll_interval=0.01,
    )


def test_ask_completes_run():
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            return FakeResponse({"run_id": "run_1", "status": "started"})
        return FakeResponse({"status": "completed", "output": "  18  graden  "})

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        answer = asyncio.run(make_client().ask("hoe warm", 240))
    assert answer == "18 graden"
    assert calls[0] == ("POST", "http://hermes.test/v1/runs")
    assert calls[1] == ("GET", "http://hermes.test/v1/runs/run_1")


def test_ask_polls_until_completed():
    states = iter(["started", "running", "completed"])

    def fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return FakeResponse({"run_id": "run_1"})
        return FakeResponse({"status": next(states), "output": "ok"})

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        answer = asyncio.run(make_client().ask("vraag", 240))
    assert answer == "ok"


def test_ask_raises_on_failed_run():
    def fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return FakeResponse({"run_id": "run_1"})
        return FakeResponse({"status": "failed", "output": ""})

    with mock.patch("urllib.request.urlopen", fake_urlopen), \
            pytest.raises(HermesError):
        asyncio.run(make_client().ask("vraag", 240))


def test_ask_raises_on_submission_error():
    def boom(request, timeout=None):
        raise OSError("connection refused")

    with mock.patch("urllib.request.urlopen", boom), \
            pytest.raises(HermesError):
        asyncio.run(make_client().ask("vraag", 240))


def test_ask_raises_on_empty_output():
    def fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return FakeResponse({"run_id": "run_1"})
        return FakeResponse({"status": "completed", "output": ""})

    with mock.patch("urllib.request.urlopen", fake_urlopen), \
            pytest.raises(HermesError):
        asyncio.run(make_client().ask("vraag", 240))


def test_ask_truncates_answer():
    def fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return FakeResponse({"run_id": "run_1"})
        return FakeResponse({"status": "completed", "output": "x" * 300})

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        answer = asyncio.run(make_client().ask("vraag", 240))
    assert len(answer) == 240
