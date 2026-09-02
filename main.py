import os
from datetime import date as date_cls

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from ha_client import HAClient, HAError
from hermes_client import HermesClient, HermesError
from weather import WeatherClient, WeatherError

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="{time:DD-MM-YYYY at HH:mm:ss} | {level: <8} | {message}",
)


class Settings(BaseSettings):
    model_config = {
        "env_file": os.getenv("STICKY_BRIDGE_ENV_FILE", ".env")
    }

    bridge_token: str = ""
    log_level: str = "INFO"
    ha_url: str = "http://192.168.68.105:8123"
    ha_token: str = ""
    ha_timezone: str = "Europe/Amsterdam"
    agenda_calendar_entities: str = "calendar.calendar"
    agenda_max_events: int = 6
    agenda_title_max_len: int = 40
    open_meteo_base_url: str = "https://api.open-meteo.com"
    weather_latitude: float = 52.0907
    weather_longitude: float = 5.1214
    hermes_url: str = "http://192.168.68.105:8642"
    hermes_api_key: str = ""
    hermes_model: str = "hermes-agent"
    chat_max_answer_chars: int = 240


settings = Settings()

app = FastAPI(title="sticky-bridge", version="0.1.0")

VERSION = "0.1.0"


def require_token(x_bridge_token: str = Header(default="")) -> None:
    if not settings.bridge_token:
        logger.error("BRIDGE_TOKEN not configured; refusing request")
        raise HTTPException(status_code=503, detail="Bridge token not configured")
    if x_bridge_token != settings.bridge_token:
        raise HTTPException(status_code=401, detail="Invalid bridge token")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code} "
        f"from {request.client.host if request.client else 'unknown'}"
    )
    return response


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "sticky-bridge", "version": VERSION}


@app.get("/api/agenda/today", dependencies=[Depends(require_token)])
async def agenda_today(date: str | None = Query(default=None)) -> dict:
    if not settings.ha_token:
        raise HTTPException(status_code=503, detail="HA_TOKEN not configured")
    entities = [
        e.strip()
        for e in settings.agenda_calendar_entities.split(",")
        if e.strip()
    ]
    day = None
    if date:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    client = HAClient(settings.ha_url, settings.ha_token, settings.ha_timezone)
    try:
        day_str, events = await client.fetch_today(
            entities, settings.agenda_max_events, settings.agenda_title_max_len, day
        )
    except (HAError, OSError, TimeoutError, ValueError) as exc:
        logger.error(f"agenda fetch failed: {exc}")
        raise HTTPException(status_code=502, detail="Home Assistant unavailable")
    return {"date": day_str, "events": events}


@app.get("/api/agenda/debug", dependencies=[Depends(require_token)])
async def agenda_debug(date: str | None = Query(default=None)) -> dict:
    if not settings.ha_token:
        raise HTTPException(status_code=503, detail="HA_TOKEN not configured")
    entities = [
        e.strip()
        for e in settings.agenda_calendar_entities.split(",")
        if e.strip()
    ]
    for probe in ("calendar.calendar",):
        if probe not in entities:
            entities.append(probe)
    day = None
    if date:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    client = HAClient(settings.ha_url, settings.ha_token, settings.ha_timezone)
    day_str, rows = await client.fetch_debug(entities, day)
    return {"date": day_str, "calendars": rows}


_weather_client = WeatherClient(
    settings.open_meteo_base_url,
    settings.weather_latitude,
    settings.weather_longitude,
)


@app.get("/api/home/status", dependencies=[Depends(require_token)])
async def home_status() -> dict:
    try:
        weather = await _weather_client.current()
    except WeatherError as exc:
        logger.error(f"weather fetch failed: {exc}")
        raise HTTPException(status_code=502, detail="Weather unavailable")
    return {"weather": weather}


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)


_hermes_client = HermesClient(
    settings.hermes_url, settings.hermes_api_key, settings.hermes_model
)


@app.post("/api/chat", dependencies=[Depends(require_token)])
async def chat(request: ChatRequest) -> dict:
    if not settings.hermes_api_key:
        raise HTTPException(status_code=503, detail="HERMES_API_KEY not set")
    try:
        answer = await _hermes_client.ask(
            request.question, settings.chat_max_answer_chars
        )
    except HermesError:
        raise HTTPException(status_code=502, detail="Hermes unavailable")
    return {"answer": answer}
