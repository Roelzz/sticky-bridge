import asyncio
import json
import time
import urllib.request

from loguru import logger

_WMO_DUTCH = {
    0: "helder",
    1: "licht bewolkt",
    2: "half bewolkt",
    3: "bewolkt",
    45: "mist",
    48: "nevel",
    51: "motregen",
    53: "motregen",
    55: "motregen",
    56: "motijzel",
    57: "motijzel",
    61: "regen",
    63: "regen",
    65: "zware regen",
    66: "ijzel",
    67: "ijzel",
    71: "sneeuw",
    73: "sneeuw",
    75: "zware sneeuw",
    77: "sneeuw",
    80: "buien",
    81: "buien",
    82: "zware buien",
    85: "sneeuwbuien",
    86: "sneeuwbuien",
    95: "onweer",
    96: "onweer met hagel",
    99: "onweer met hagel",
}


class WeatherError(RuntimeError):
    pass


def wmo_text(code: int) -> str:
    return _WMO_DUTCH.get(code, f"code {code}")


class WeatherClient:
    def __init__(self, base_url: str, lat: float, lon: float,
                 cache_ttl_s: int = 1800, timeout: float = 8.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._lat = lat
        self._lon = lon
        self._ttl = cache_ttl_s
        self._timeout = timeout
        self._cached: dict | None = None
        self._cached_at = 0.0

    def _fetch(self) -> dict:
        url = (
            f"{self._base_url}/v1/forecast?latitude={self._lat}"
            f"&longitude={self._lon}"
            "&current=temperature_2m,relative_humidity_2m,weather_code"
            "&timezone=Europe%2FAmsterdam"
        )
        with urllib.request.urlopen(url, timeout=self._timeout) as response:
            payload = json.loads(response.read())
        current = payload.get("current") or {}
        temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        code = current.get("weather_code")
        if temp is None or code is None:
            raise WeatherError(f"unexpected open-meteo payload: {payload}")
        return {
            "temp": round(float(temp), 1),
            "humidity": int(humidity) if humidity is not None else None,
            "code": int(code),
            "text": wmo_text(int(code)),
        }

    async def current(self) -> dict:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached
        try:
            self._cached = await asyncio.to_thread(self._fetch)
            self._cached_at = now
        except (OSError, ValueError) as exc:
            logger.warning(f"open-meteo fetch failed: {exc}")
            if self._cached is not None:
                return self._cached
            raise WeatherError(str(exc)) from exc
        return self._cached
