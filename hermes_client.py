import asyncio
import json
import urllib.request

from loguru import logger

_INSTRUCTION = (
    "Beantwoord in maximaal 120 karakters, in het Nederlands, "
    "zonder opmaak."
)
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "stopped"}


class HermesError(RuntimeError):
    pass


class HermesClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 overall_timeout: float = 150.0,
                 poll_interval: float = 3.0,
                 request_timeout: float = 20.0,
                 stream_read_timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._overall_timeout = overall_timeout
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout
        self._stream_read_timeout = stream_read_timeout

    def _request(self, method: str, path: str,
                 payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request,
                                    timeout=self._request_timeout) as resp:
            return json.loads(resp.read())

    def _submit_run(self, question: str) -> str:
        result = self._request("POST", "/v1/runs", {
            "model": self._model,
            "input": f"{question}\n\n{_INSTRUCTION}",
        })
        run_id = result.get("run_id", "")
        if not run_id:
            raise HermesError("hermes returned no run_id")
        return run_id

    def _run_status(self, run_id: str) -> dict:
        return self._request("GET", f"/v1/runs/{run_id}")

    def _open_stream(self, question: str):
        request = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps({
                "model": self._model,
                "stream": True,
                "messages": [{
                    "role": "user",
                    "content": f"{question}\n\n{_INSTRUCTION}",
                }],
            }).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            return urllib.request.urlopen(
                request, timeout=self._stream_read_timeout)
        except OSError as exc:
            logger.error(f"hermes stream request failed: {exc}")
            raise HermesError(str(exc)) from exc

    def stream_ask(self, question: str,
                   max_answer_chars: int):
        response = self._open_stream(question)
        total = 0
        with response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    logger.warning(f"unparsable sse event: {data[:80]}")
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if not content:
                    continue
                remaining = max_answer_chars - total
                if remaining <= 0:
                    break
                piece = content[:remaining]
                total += len(piece)
                yield piece

    async def ask(self, question: str, max_answer_chars: int) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._overall_timeout
        try:
            run_id = await asyncio.to_thread(self._submit_run, question)
        except (OSError, ValueError) as exc:
            logger.error(f"hermes run submission failed: {exc}")
            raise HermesError(str(exc)) from exc
        logger.info(f"hermes run submitted: {run_id}")
        status: dict = {}
        while True:
            try:
                status = await asyncio.to_thread(self._run_status, run_id)
            except (OSError, ValueError) as exc:
                logger.error(f"hermes run poll failed: {exc}")
                raise HermesError(str(exc)) from exc
            if status.get("status") in _TERMINAL_STATUSES:
                break
            if loop.time() >= deadline:
                raise HermesError(f"hermes run {run_id} timed out")
            await asyncio.sleep(self._poll_interval)
        if status.get("status") != "completed":
            raise HermesError(
                f"hermes run {run_id} ended as {status.get('status')}"
            )
        output = " ".join(str(status.get("output", "")).split())
        if not output:
            raise HermesError("empty run output")
        return output[:max_answer_chars]
