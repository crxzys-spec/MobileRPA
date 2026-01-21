import json
import logging
from typing import Awaitable, Callable, Optional

from fastapi import WebSocket


JsonHandler = Callable[[dict], Awaitable[None]]
AsyncCallback = Callable[[], Awaitable[None]]


class JsonWsServer:
    def __init__(
        self,
        token: Optional[str] = None,
        *,
        trace: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._token = token
        self._trace = trace
        self._logger = logger or logging.getLogger("mrpa.ws.server")

    async def handle(
        self,
        websocket: WebSocket,
        on_message: JsonHandler,
        *,
        on_connect: Optional[AsyncCallback] = None,
        on_disconnect: Optional[AsyncCallback] = None,
    ) -> None:
        if self._token:
            token = websocket.query_params.get("token")
            if token != self._token:
                await websocket.close(code=1008)
                return
        await websocket.accept()
        if on_connect:
            await on_connect()
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    self._log("rx", payload)
                    try:
                        await on_message(payload)
                    except Exception:
                        self._logger.exception("ws handler error")
        except Exception:
            pass
        finally:
            if on_disconnect:
                await on_disconnect()

    def _log(self, direction: str, payload: dict) -> None:
        if not self._trace:
            return
        summary = _summarize(payload)
        self._logger.info("ws %s %s", direction, summary)


def _summarize(payload: dict) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    keys = ("type", "request_id", "device_id", "client_id")
    summary = {key: payload.get(key) for key in keys if payload.get(key)}
    if not summary:
        summary = {"keys": list(payload.keys())[:6]}
    return json.dumps(summary, ensure_ascii=True)
