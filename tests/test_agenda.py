import asyncio

import pytest
from fastapi.testclient import TestClient

import main
from ha_client import HAClient, HAError, _to_calendar_event, normalize_events

TEST_TOKEN = "test-token-abc"


@pytest.fixture()
def token_secret(monkeypatch):
    monkeypatch.setattr(main.settings, "bridge_token", TEST_TOKEN)


@pytest.fixture()
def ha_configured(monkeypatch):
    monkeypatch.setattr(main.settings, "ha_token", "ha-secret")


def _client() -> TestClient:
    return TestClient(main.app)


def test_agenda_rejects_missing_token(token_secret):
    response = _client().get("/api/agenda/today")
    assert response.status_code == 401


def test_agenda_fails_closed_without_ha_token(token_secret):
    monkey_response = _client().get(
        "/api/agenda/today", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert monkey_response.status_code == 503


def test_agenda_returns_events(token_secret, ha_configured, monkeypatch):
    async def fake_fetch_today(self, entities, max_events, title_max_len, day=None):
        assert entities == ["calendar.calendar"]
        return "2026-09-01", [{"t": "09:30", "title": "Standup"}]

    monkeypatch.setattr(main.HAClient, "fetch_today", fake_fetch_today)
    response = _client().get(
        "/api/agenda/today", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert response.status_code == 200
    assert response.json() == {
        "date": "2026-09-01",
        "events": [{"t": "09:30", "title": "Standup"}],
    }


def test_agenda_bad_gateway_on_ha_failure(token_secret, ha_configured, monkeypatch):
    async def broken_fetch(self, entities, max_events, title_max_len, day=None):
        raise HAError("boom")

    monkeypatch.setattr(main.HAClient, "fetch_today", broken_fetch)
    response = _client().get(
        "/api/agenda/today", headers={"X-Bridge-Token": TEST_TOKEN}
    )
    assert response.status_code == 502


def test_normalize_sorts_timed_after_allday_and_caps():
    events = [
        {"summary": "Laat", "start": {"dateTime": "2026-09-01T18:00:00+02:00"}},
        {"summary": "Hele dag ding", "start": {"date": "2026-09-01"}},
        {"summary": "Vroeg", "start": {"dateTime": "2026-09-01T07:15:00+02:00"}},
        {"summary": "Tweede", "start": {"dateTime": "2026-09-01T07:20:00+02:00"}},
    ]
    result = normalize_events(events, max_events=3, title_max_len=40)
    assert result == [
        {"t": "hele dag", "title": "Hele dag ding"},
        {"t": "07:15", "title": "Vroeg"},
        {"t": "07:20", "title": "Tweede"},
    ]


def test_normalize_truncates_title_and_defaults_summary():
    events = [
        {"summary": "X" * 60, "start": {"dateTime": "2026-09-01T10:00:00+02:00"}},
        {"start": {"date": "2026-09-01"}},
    ]
    result = normalize_events(events, max_events=6, title_max_len=40)
    assert result[0]["title"] == "(titelloos)"
    assert len(result[1]["title"]) == 40


def test_to_calendar_event_converts_service_payloads():
    timed = _to_calendar_event(
        {"summary": "Lunch", "start": "2026-09-02T12:00:00+02:00"}
    )
    allday = _to_calendar_event({"summary": "Holiday", "start": "2026-09-02"})
    native = _to_calendar_event(
        {"summary": "Legacy", "start": {"dateTime": "2026-09-02T09:00:00+02:00"}}
    )
    assert timed["start"] == {"dateTime": "2026-09-02T12:00:00+02:00"}
    assert allday["start"] == {"date": "2026-09-02"}
    assert native["start"] == {"dateTime": "2026-09-02T09:00:00+02:00"}


def test_fetch_debug_reports_per_entity(monkeypatch):
    client = HAClient("http://ha.test", "tok", "Europe/Amsterdam")

    def fake_get_events(self, entity, start_iso, end_iso):
        if entity == "calendar.broken":
            raise HAError("HTTP 404")
        return [{"summary": "X", "start": {"date": "2026-09-02"}}]

    monkeypatch.setattr(HAClient, "_get_events", fake_get_events)
    day, rows = asyncio.run(client.fetch_debug(["calendar.ok", "calendar.broken"]))
    assert day
    assert rows[0] == {"entity": "calendar.ok", "ok": True, "count": 1, "error": None}
    assert rows[1]["ok"] is False
    assert "404" in rows[1]["error"]
