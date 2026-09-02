import pytest
from fastapi.testclient import TestClient

import main
from weather import WeatherClient, WeatherError, wmo_text

TEST_TOKEN = "test-token-abc"

WEATHER = {"temp": 18.4, "humidity": 65, "code": 3, "text": "bewolkt"}


@pytest.fixture()
def token_secret(monkeypatch):
    monkeypatch.setattr(main.settings, "bridge_token", TEST_TOKEN)


def test_home_status_rejects_missing_token(token_secret):
    response = TestClient(main.app).get("/api/home/status")
    assert response.status_code == 401


def test_home_status_returns_weather(token_secret, monkeypatch):
    async def fake_current(self):
        return WEATHER

    monkeypatch.setattr(WeatherClient, "current", fake_current)
    response = TestClient(main.app).get(
        "/api/home/status", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert response.status_code == 200
    assert response.json() == {"weather": WEATHER}


def test_home_status_bad_gateway_on_weather_failure(token_secret, monkeypatch):
    async def broken_current(self):
        raise WeatherError("offline")

    monkeypatch.setattr(WeatherClient, "current", broken_current)
    response = TestClient(main.app).get(
        "/api/home/status", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert response.status_code == 502


def test_wmo_text_known_and_unknown_codes():
    assert wmo_text(0) == "helder"
    assert wmo_text(95) == "onweer"
    assert wmo_text(123) == "code 123"


def test_weather_client_cache_serves_second_call(monkeypatch):
    client = WeatherClient("https://example.invalid", 52.0, 5.0)
    calls = []

    def fake_fetch():
        calls.append(1)
        return WEATHER

    monkeypatch.setattr(client, "_fetch", fake_fetch)
    import asyncio

    asyncio.run(client.current())
    asyncio.run(client.current())
    assert len(calls) == 1
