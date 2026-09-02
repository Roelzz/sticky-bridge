import asyncio
import json
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger


class HAError(RuntimeError):
    pass


def _to_calendar_event(event: dict) -> dict:
    summary = event.get("summary")
    start = event.get("start")
    if isinstance(start, dict):
        return {"summary": summary, "start": start}
    if isinstance(start, str):
        key = "dateTime" if "T" in start else "date"
        return {"summary": summary, "start": {key: start}}
    return {"summary": summary, "start": {}}


class HAClient:
    def __init__(
        self, url: str, token: str, timezone: str, timeout: float = 10.0
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timezone = timezone
        self._timeout = timeout

    def _get_events(self, entity: str, start_iso: str, end_iso: str) -> list[dict]:
        body = json.dumps(
            {
                "entity_id": entity,
                "start_date_time": start_iso,
                "end_date_time": end_iso,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._url}/api/services/calendar/get_events?return_response",
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            payload = json.loads(response.read())
        result = payload.get("service_response", {}).get(entity)
        if isinstance(result, dict):
            raw = result.get("events", [])
        elif isinstance(result, list):
            raw = result
        else:
            raise HAError(f"no service_response for {entity}")
        return [_to_calendar_event(e) for e in raw]

    def _day_bounds(self, day: date | None) -> tuple[str, str, str]:
        tz = ZoneInfo(self._timezone)
        start = (
            datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            if day is None
            else datetime(day.year, day.month, day.day, tzinfo=tz)
        )
        end = start + timedelta(days=1)
        return start.date().isoformat(), start.isoformat(), end.isoformat()

    async def fetch_today(
        self,
        entities: list[str],
        max_events: int,
        title_max_len: int,
        day: date | None = None,
    ) -> tuple[str, list[dict]]:
        today, start_iso, end_iso = self._day_bounds(day)

        events: list[dict] = []
        for entity in entities:
            try:
                events.extend(
                    await asyncio.to_thread(
                        self._get_events, entity, start_iso, end_iso
                    )
                )
            except (OSError, ValueError, HAError) as exc:
                logger.warning(f"calendar {entity} fetch failed: {exc}")
        return today, normalize_events(events, max_events, title_max_len)

    async def fetch_debug(
        self, entities: list[str], day: date | None = None
    ) -> tuple[str, list[dict]]:
        today, start_iso, end_iso = self._day_bounds(day)
        rows: list[dict] = []
        for entity in entities:
            row = {"entity": entity, "ok": False, "count": 0, "error": None}
            try:
                events = await asyncio.to_thread(
                    self._get_events, entity, start_iso, end_iso
                )
                row["ok"] = True
                row["count"] = len(events)
            except (OSError, ValueError, HAError) as exc:
                row["error"] = str(exc)[:200]
            rows.append(row)
        return today, rows


def normalize_events(
    events: list[dict], max_events: int, title_max_len: int
) -> list[dict]:
    rows: list[tuple[str, str, str]] = []
    for event in events:
        start = event.get("start") or {}
        summary = (event.get("summary") or "(titelloos)")[:title_max_len]
        if "dateTime" in start:
            time_text = _format_time(start["dateTime"])
            sort_key = time_text
        else:
            time_text = "hele dag"
            sort_key = "00:00"
        rows.append((sort_key, time_text, summary))
    rows.sort()
    return [{"t": t, "title": title} for _, t, title in rows[:max_events]]


def _format_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        logger.warning(f"unparsable event start: {iso}")
        return "??:??"
