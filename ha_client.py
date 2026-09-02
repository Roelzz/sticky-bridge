import asyncio
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger


class HAError(RuntimeError):
    pass


class HAClient:
    def __init__(
        self, url: str, token: str, timezone: str, timeout: float = 10.0
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timezone = timezone
        self._timeout = timeout

    def _get_json(self, path: str, params: dict[str, str]) -> Any:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self._url}{path}?{query}",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    async def fetch_today(
        self,
        entities: list[str],
        max_events: int,
        title_max_len: int,
        day: date | None = None,
    ) -> tuple[str, list[dict]]:
        tz = ZoneInfo(self._timezone)
        start = (
            datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            if day is None
            else datetime(day.year, day.month, day.day, tzinfo=tz)
        )
        end = start + timedelta(days=1)
        today = start.date().isoformat()

        events: list[dict] = []
        for entity in entities:
            try:
                events.extend(
                    await asyncio.to_thread(
                        self._get_json,
                        f"/api/calendars/{entity}",
                        {
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        },
                    )
                )
            except (OSError, ValueError) as exc:
                logger.warning(f"calendar {entity} fetch failed: {exc}")
        return today, normalize_events(events, max_events, title_max_len)


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
