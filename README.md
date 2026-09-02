# sticky-bridge

HTTP bridge between reTerminal Sticky firmware and the homelab. The Sticky only ever calls this service; Home Assistant and Hermes stay off the device.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness, used by firmware wire test |
| GET | `/agenda` | `X-Bridge-Token` | Today's calendar events (phase 2) |
| GET | `/dashboard` | `X-Bridge-Token` | Lights, temperatures, item locations (phase 3) |
| POST | `/voice` | `X-Bridge-Token` | WAV in, transcript + Hermes reply out (phase 5) |

Auth: all non-public routes require the `X-Bridge-Token` header to match `BRIDGE_TOKEN`. Fails closed with 503 if the token is not configured.

## Run locally

```bash
uv sync
cp .env.example .env  # set BRIDGE_TOKEN (openssl rand -hex 24)
uv run uvicorn main:app --port 8070
uv run pytest
```

## Deploy

`docker compose up -d` on the homelab server (port **8070** is fixed for this project).

## Environment

| Variable | Required | Description |
|---|---|---|
| `BRIDGE_TOKEN` | yes | Shared secret, firmware sends it as `X-Bridge-Token` |
| `LOG_LEVEL` | no | Default `INFO` |

HA/Hermes/STT config keys are added with their respective phases.

## Network note

Wheels were resolved via the TUNA PyPI mirror (this machine's network blocks `files.pythonhosted.org`). `uv.lock` download URLs point at the mirror; re-lock once the network issue is resolved.
