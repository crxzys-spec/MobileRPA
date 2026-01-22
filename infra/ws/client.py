import asyncio
import contextlib
import json
import logging
from typing import Any, Awaitable, Callable, Optional


JsonHandler = Callable[[dict], Awaitable[None]]
AsyncCallback = Callable[[], Awaitable[None]]


class JsonWsClient:
    def __init__(
        self,
        url: str,
        *,
        token: Optional[str] = None,
        heartbeat: float = 5.0,
        reconnect_delay: float = 2.0,
        trace: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._url = url
        self._token = token
        self._heartbeat = heartbeat
        self._reconnect_delay = reconnect_delay
        self._trace = trace
        self._logger = logger or logging.getLogger("mrpa.ws.client")
        self._stop_event = asyncio.Event()
        self._ws = None
        self._lock = asyncio.Lock()

    async def run(
        self,
        on_connect: Optional[AsyncCallback],
        on_message: JsonHandler,
        on_disconnect: Optional[AsyncCallback],
        *,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        stop_event = stop_event or self._stop_event
        while not stop_event.is_set():
            try:
                await self._connect_once(
                    on_connect, on_message, on_disconnect, stop_event=stop_event
                )
            except Exception:
                if stop_event.is_set():
                    break
                await asyncio.sleep(self._reconnect_delay)
                continue
            if stop_event.is_set():
                break
            await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        self._stop_event.set()
        ws = None
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=1)
            ws = self._ws
        except asyncio.TimeoutError:
            ws = self._ws
        finally:
            if self._lock.locked():
                self._lock.release()
        if ws is not None:
            try:
                await asyncio.wait_for(ws.close(), timeout=2)
            except Exception:
                pass

    async def send(self, payload: dict) -> None:
        async with self._lock:
            if self._ws is None:
                raise RuntimeError("websocket not connected")
            self._log("tx", payload)
            await self._ws.send_json(payload)

    async def _connect_once(
        self,
        on_connect: Optional[AsyncCallback],
        on_message: JsonHandler,
        on_disconnect: Optional[AsyncCallback],
        *,
        stop_event: asyncio.Event,
    ) -> None:
        aiohttp = _load_aiohttp()
        ws_url = self._url
        if self._token:
            joiner = "&" if "?" in ws_url else "?"
            ws_url = "{}{}token={}".format(ws_url, joiner, self._token)
        async with aiohttp.ClientSession() as session:
            stop_task = asyncio.create_task(stop_event.wait())
            connect_task = asyncio.create_task(
                session.ws_connect(ws_url, heartbeat=self._heartbeat)
            )
            done, pending = await asyncio.wait(
                {connect_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                connect_task.cancel()
                with contextlib.suppress(Exception):
                    await connect_task
                return
            ws = connect_task.result()
            async with ws:
                async with self._lock:
                    self._ws = ws
                self._log("connect", {"url": ws_url})
                if on_connect:
                    await on_connect()
                try:
                    while True:
                        if stop_event.is_set():
                            await ws.close()
                            break
                        recv_task = asyncio.create_task(ws.receive())
                        done, pending = await asyncio.wait(
                            {recv_task, stop_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop_task in done:
                            recv_task.cancel()
                            await ws.close()
                            break
                        msg = recv_task.result()
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = _parse_json(msg.data)
                            if payload is not None:
                                self._log("rx", payload)
                                await on_message(payload)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                finally:
                    stop_task.cancel()
                    async with self._lock:
                        self._ws = None
                    self._log("disconnect", {"url": ws_url})
                    if on_disconnect:
                        await on_disconnect()

    def _log(self, direction: str, payload: dict) -> None:
        if not self._trace:
            return
        summary = _summarize(payload)
        self._logger.info("ws %s %s", direction, summary)


def _parse_json(text: str) -> Optional[dict]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _summarize(payload: dict) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    keys = ("type", "request_id", "device_id", "client_id")
    summary = {key: payload.get(key) for key in keys if payload.get(key)}
    if not summary:
        summary = {"keys": list(payload.keys())[:6]}
    return json.dumps(summary, ensure_ascii=True)


def _load_aiohttp():
    try:
        import aiohttp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "aiohttp is required for websocket client"
        ) from exc
    return aiohttp
