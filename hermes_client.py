import asyncio
import json
import urllib.request

from loguru import logger


class HermesError(RuntimeError):
    pass


class HermesClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: float = 75.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as resp:
            return json.loads(resp.read())

    async def ask(self, question: str, max_answer_chars: int) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Je bent een korte-hulpassistent voor een "
                        "e-ink-scherm van het formaat een creditcard. "
                        "Antwoord in maximaal 120 karakters, in het "
                        "Nederlands, zonder opmaak."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "max_tokens": 160,
            "temperature": 0.3,
        }
        try:
            result = await asyncio.to_thread(self._post, payload)
        except (OSError, ValueError) as exc:
            logger.error(f"hermes request failed: {exc}")
            raise HermesError(str(exc)) from exc
        choices = result.get("choices") or []
        content = (choices[0].get("message") or {}).get("content", "") \
            if choices else ""
        if not content:
            raise HermesError("empty completion")
        return " ".join(content.split())[:max_answer_chars]
