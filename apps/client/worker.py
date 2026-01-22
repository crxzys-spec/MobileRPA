import asyncio
import contextlib
import logging
import socket
import uuid
from typing import Any, Dict, Optional

from infra.ws.client import JsonWsClient
from mrpa.api.schemas import WebRTCOffer
from mrpa.domains.device import DeviceCommand, DeviceSessionManager
from mrpa.domains.stream import list_devices as list_adb_devices
from mrpa.domains.stream import webrtc_offer
from mrpa.domains.stream.scrcpy_sessions import (
    ScrcpySessionConfig,
    ScrcpySessionManager,
    ScrcpySessionStatus,
)

from .settings import ClientServiceSettings


class ClientWorker:
    def __init__(
        self,
        settings: ClientServiceSettings,
        device_manager: DeviceSessionManager,
        scrcpy_sessions: Optional[ScrcpySessionManager] = None,
    ) -> None:
        self._settings = settings
        self._device_manager = device_manager
        self._scrcpy_sessions = scrcpy_sessions
        self._client_id = settings.client_id or socket.gethostname()
        self._logger = logging.getLogger("mrpa.client.worker")
        self._stop_event = asyncio.Event()
        self._client = JsonWsClient(
            settings.mrpa_ws_url,
            token=settings.token,
            heartbeat=settings.heartbeat,
            reconnect_delay=settings.reconnect_delay,
            trace=settings.ws_trace,
        )
        self._update_task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        await self._client.run(
            self._on_connect,
            self._on_message,
            self._on_disconnect,
            stop_event=self._stop_event,
        )

    async def shutdown(self) -> None:
        self._stop_event.set()
        await self._client.stop()

    async def _on_connect(self) -> None:
        try:
            await self._send_register()
        except Exception:
            self._logger.exception("ws register failed")
        self._update_task = asyncio.create_task(self._periodic_update())

    async def _on_disconnect(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(Exception):
                await self._update_task
        self._update_task = None

    async def _on_message(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "command":
            await self._handle_command(data)
            return
        if msg_type == "queue_clear":
            await self._handle_queue_clear(data)
            return
        if msg_type == "session_close":
            await self._handle_session_close(data)
            return
        if msg_type == "webrtc_offer":
            await self._handle_webrtc_offer(data)
            return
        if msg_type == "stream_session_start":
            await self._handle_stream_session_start(data)
            return
        if msg_type == "stream_session_stop":
            await self._handle_stream_session_stop(data)
            return
        if msg_type == "stream_session_restart":
            await self._handle_stream_session_restart(data)
            return
        if msg_type == "stream_session_config":
            await self._handle_stream_session_config(data)

    async def _send(self, payload: Dict[str, Any]) -> None:
        try:
            await self._client.send(payload)
        except RuntimeError:
            return

    async def _handle_command(self, data: Dict[str, Any]) -> None:
        device_id = data.get("device_id")
        command_payload = data.get("command") or {}
        command_type = command_payload.get("type")
        if not device_id or not command_type:
            return
        command_id = command_payload.get("id") or uuid.uuid4().hex
        payload = {
            key: value
            for key, value in command_payload.items()
            if key not in ("id", "type")
        }
        command = DeviceCommand(
            command_type=str(command_type),
            payload=payload,
            id=command_id,
        )
        session = self._device_manager.get_or_create(device_id)
        session.enqueue(command)
        await self._send(
            {
                "type": "command_update",
                "device_id": device_id,
                "command": command.to_dict(),
            }
        )
        asyncio.create_task(self._watch_command(device_id, command))

    async def _watch_command(self, device_id: str, command: DeviceCommand) -> None:
        last_status = command.status
        while command.status in ("queued", "running"):
            if command.status != last_status:
                last_status = command.status
                await self._send(
                    {
                        "type": "command_update",
                        "device_id": device_id,
                        "command": command.to_dict(),
                    }
                )
            await asyncio.sleep(self._settings.command_poll_interval)
        await self._send(
            {
                "type": "command_update",
                "device_id": device_id,
                "command": command.to_dict(),
            }
        )
        session = self._device_manager.get_session(device_id)
        if session:
            await self._send(
                {"type": "session_update", "session": session.status_dict()}
            )

    async def _handle_queue_clear(self, data: Dict[str, Any]) -> None:
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        drained = self._device_manager.clear_queue(device_id)
        await self._send(
            {
                "type": "queue_clear_result",
                "request_id": request_id,
                "device_id": device_id,
                "drained": drained,
            }
        )

    async def _handle_session_close(self, data: Dict[str, Any]) -> None:
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        closed = self._device_manager.close(device_id)
        await self._send(
            {
                "type": "session_close_result",
                "request_id": request_id,
                "device_id": device_id,
                "closed": closed,
            }
        )

    async def _handle_webrtc_offer(self, data: Dict[str, Any]) -> None:
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        sdp = data.get("sdp")
        sdp_type = data.get("sdp_type") or "offer"
        if not device_id or not request_id or not sdp:
            return
        session = self._device_manager.get_or_create(device_id)
        asyncio.create_task(asyncio.to_thread(session.warmup_control))
        try:
            offer = WebRTCOffer(sdp=sdp, type=sdp_type, device_id=device_id)
            answer = await webrtc_offer(offer)
            payload = {
                "type": "webrtc_answer",
                "request_id": request_id,
                "sdp": answer.sdp,
                "sdp_type": answer.type,
            }
        except Exception as exc:
            payload = {
                "type": "webrtc_answer",
                "request_id": request_id,
                "error": str(exc),
            }
        await self._send(payload)

    def _merge_stream_config(
        self, device_id: str, payload: Optional[Dict[str, Any]]
    ) -> ScrcpySessionConfig:
        if not self._scrcpy_sessions:
            raise RuntimeError("scrcpy sessions not available")
        base = self._scrcpy_sessions.get_config(device_id)
        data = base.as_dict()
        if payload:
            for key, value in payload.items():
                if value is not None:
                    data[key] = value
        return ScrcpySessionConfig(**data)

    async def _handle_stream_session_start(self, data: Dict[str, Any]) -> None:
        if not self._scrcpy_sessions:
            return
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        try:
            config = self._merge_stream_config(device_id, data.get("config"))
            status = self._scrcpy_sessions.start(device_id, config)
            payload = {
                "type": "stream_session_result",
                "request_id": request_id,
                "session": status.as_dict(),
            }
            await self._send(payload)
            await self._send(
                {"type": "stream_session_update", "session": status.as_dict()}
            )
        except Exception as exc:
            await self._send(
                {
                    "type": "stream_session_result",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )

    async def _handle_stream_session_stop(self, data: Dict[str, Any]) -> None:
        if not self._scrcpy_sessions:
            return
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        try:
            status = self._scrcpy_sessions.stop(device_id)
            payload = {
                "type": "stream_session_result",
                "request_id": request_id,
                "session": status.as_dict(),
            }
            await self._send(payload)
            await self._send(
                {"type": "stream_session_update", "session": status.as_dict()}
            )
        except Exception as exc:
            await self._send(
                {
                    "type": "stream_session_result",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )

    async def _handle_stream_session_restart(self, data: Dict[str, Any]) -> None:
        if not self._scrcpy_sessions:
            return
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        try:
            config = self._merge_stream_config(device_id, data.get("config"))
            status = self._scrcpy_sessions.restart(device_id, config)
            payload = {
                "type": "stream_session_result",
                "request_id": request_id,
                "session": status.as_dict(),
            }
            await self._send(payload)
            await self._send(
                {"type": "stream_session_update", "session": status.as_dict()}
            )
        except Exception as exc:
            await self._send(
                {
                    "type": "stream_session_result",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )

    async def _handle_stream_session_config(self, data: Dict[str, Any]) -> None:
        if not self._scrcpy_sessions:
            return
        device_id = data.get("device_id")
        request_id = data.get("request_id")
        if not device_id or not request_id:
            return
        try:
            config = self._merge_stream_config(device_id, data.get("config"))
            session = self._scrcpy_sessions.get_session(device_id)
            if session and session.status().status in ("running", "starting"):
                payload_session = self._scrcpy_sessions.restart(
                    device_id, config
                ).as_dict()
            else:
                self._scrcpy_sessions.set_config(device_id, config)
                if session:
                    payload_session = session.status().as_dict()
                else:
                    payload_session = ScrcpySessionStatus(
                        device_id=device_id,
                        status="stopped",
                        config=config,
                    ).as_dict()
            await self._send(
                {
                    "type": "stream_session_result",
                    "request_id": request_id,
                    "session": payload_session,
                }
            )
            await self._send(
                {"type": "stream_session_update", "session": payload_session}
            )
        except Exception as exc:
            await self._send(
                {
                    "type": "stream_session_result",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )

    async def _send_register(self) -> None:
        devices = self._collect_devices()
        self._ensure_sessions(devices)
        sessions = self._device_manager.list_sessions()
        stream_sessions = self._collect_stream_sessions(devices)
        await self._send(
            {
                "type": "register",
                "client_id": self._client_id,
                "devices": devices,
                "sessions": sessions,
                "stream_sessions": stream_sessions,
                "capabilities": {
                    "webrtc": True,
                    "commands": True,
                    "scrcpy_sessions": bool(self._scrcpy_sessions),
                },
            }
        )

    async def _periodic_update(self) -> None:
        while not self._stop_event.is_set():
            try:
                devices = self._collect_devices()
                self._ensure_sessions(devices)
                sessions = self._device_manager.list_sessions()
                await self._send({"type": "devices_update", "devices": devices})
                await self._send({"type": "sessions_update", "sessions": sessions})
                stream_sessions = self._collect_stream_sessions(devices)
                if stream_sessions:
                    await self._send(
                        {
                            "type": "stream_sessions_update",
                            "stream_sessions": stream_sessions,
                        }
                    )
            except Exception:
                self._logger.exception("ws update failed")
            await asyncio.sleep(self._settings.device_refresh)

    def _collect_stream_sessions(
        self, devices: list[Dict[str, Any]]
    ) -> list[Dict[str, Any]]:
        if not self._scrcpy_sessions:
            return []
        sessions = {
            item.device_id: item
            for item in self._scrcpy_sessions.list_sessions()
        }
        items: list[Dict[str, Any]] = []
        for device in devices:
            device_id = str(device.get("id") or "").strip()
            if not device_id:
                continue
            session = sessions.get(device_id)
            if session:
                items.append(session.as_dict())
                continue
            config = self._scrcpy_sessions.get_config(device_id)
            items.append(
                ScrcpySessionStatus(
                    device_id=device_id,
                    status="stopped",
                    config=config,
                ).as_dict()
            )
        return items

    def _collect_devices(self) -> list[Dict[str, Any]]:
        try:
            return list_adb_devices()
        except Exception:
            return []

    def _ensure_sessions(self, devices: list[Dict[str, Any]]) -> None:
        for device in devices:
            device_id = device.get("id")
            if device_id:
                try:
                    self._device_manager.get_or_create(device_id)
                except Exception:
                    self._logger.exception(
                        "device session init failed: %s", device_id
                    )
