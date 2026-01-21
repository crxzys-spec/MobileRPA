import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Deque, Dict, Iterable, Optional

from fastapi import HTTPException, WebSocket


CommandHistory = Deque[Dict[str, Any]]


@dataclass
class ClientState:
    client_id: str
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    connected: bool = True
    disconnected_at: Optional[float] = None
    devices: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sessions: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ClientRegistry:
    def __init__(self, history_limit: int = 200) -> None:
        self._history_limit = max(50, int(history_limit))
        self._lock = Lock()
        self._clients: Dict[str, ClientState] = {}
        self._device_index: Dict[str, str] = {}
        self._command_history: Dict[str, CommandHistory] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._pending: Dict[str, asyncio.Future] = {}

    def register(
        self,
        client_id: str,
        websocket: WebSocket,
        devices: Iterable[Dict[str, Any]],
        sessions: Iterable[Dict[str, Any]],
    ) -> None:
        now = time.time()
        devices_map = {
            str(item.get("id")): dict(item)
            for item in devices
            if item.get("id")
        }
        sessions_map = {
            str(item.get("device_id")): dict(item)
            for item in sessions
            if item.get("device_id")
        }
        with self._lock:
            existing = self._clients.get(client_id)
            if existing is not None and existing.websocket is not None:
                if existing.websocket != websocket:
                    try:
                        asyncio.create_task(
                            existing.websocket.close(code=1001)
                        )
                    except RuntimeError:
                        pass
            state = ClientState(
                client_id=client_id,
                websocket=websocket,
                connected_at=now,
                last_seen=now,
                connected=True,
                disconnected_at=None,
                devices=devices_map,
                sessions=sessions_map,
            )
            self._clients[client_id] = state
            self._rebuild_device_index()

    def mark_disconnected(self, client_id: str) -> None:
        with self._lock:
            state = self._clients.get(client_id)
            if state:
                state.connected = False
                state.disconnected_at = time.time()
                state.websocket = None
                self._rebuild_device_index()

    def evict(self, client_id: str) -> None:
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                self._rebuild_device_index()

    def touch(self, client_id: str) -> None:
        with self._lock:
            state = self._clients.get(client_id)
            if state:
                state.last_seen = time.time()

    def update_devices(
        self, client_id: str, devices: Iterable[Dict[str, Any]]
    ) -> None:
        devices_map = {
            str(item.get("id")): dict(item)
            for item in devices
            if item.get("id")
        }
        with self._lock:
            state = self._clients.get(client_id)
            if not state:
                return
            state.devices = devices_map
            state.last_seen = time.time()
            state.connected = True
            state.disconnected_at = None
            self._rebuild_device_index()

    def update_sessions(
        self, client_id: str, sessions: Iterable[Dict[str, Any]]
    ) -> None:
        sessions_map = {
            str(item.get("device_id")): dict(item)
            for item in sessions
            if item.get("device_id")
        }
        with self._lock:
            state = self._clients.get(client_id)
            if not state:
                return
            state.sessions = sessions_map
            state.last_seen = time.time()
            state.connected = True
            state.disconnected_at = None

    def update_session(self, client_id: str, session: Dict[str, Any]) -> None:
        device_id = session.get("device_id")
        if not device_id:
            return
        with self._lock:
            state = self._clients.get(client_id)
            if not state:
                return
            state.sessions[str(device_id)] = dict(session)
            state.last_seen = time.time()
            state.connected = True
            state.disconnected_at = None

    def update_command(self, device_id: str, command: Dict[str, Any]) -> None:
        if not device_id:
            return
        with self._lock:
            history = self._command_history[str(device_id)]
            command_id = command.get("id")
            if command_id:
                for idx, item in enumerate(history):
                    if item.get("id") == command_id:
                        history[idx] = dict(command)
                        return
            history.append(dict(command))

    def list_devices(self, inactive_after: Optional[float] = None) -> list[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            items: list[Dict[str, Any]] = []
            for state in self._clients.values():
                status = self._client_status(state, now, inactive_after)
                for device in state.devices.values():
                    payload = dict(device)
                    payload.setdefault("client_id", state.client_id)
                    payload.setdefault("client_status", status)
                    payload.setdefault("client_last_seen", state.last_seen)
                    items.append(payload)
            return items

    def list_sessions(self, inactive_after: Optional[float] = None) -> list[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            items: list[Dict[str, Any]] = []
            for state in self._clients.values():
                status = self._client_status(state, now, inactive_after)
                for session in state.sessions.values():
                    payload = dict(session)
                    payload.setdefault("client_id", state.client_id)
                    payload.setdefault("client_status", status)
                    payload.setdefault("client_last_seen", state.last_seen)
                    items.append(payload)
            return items

    def get_session(
        self, device_id: str, inactive_after: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            client_id = self._device_index.get(device_id)
            if not client_id:
                return None
            state = self._clients.get(client_id)
            if not state:
                return None
            session = state.sessions.get(device_id)
            if not session:
                return None
            status = self._client_status(state, now, inactive_after)
            payload = dict(session)
            payload.setdefault("client_id", client_id)
            payload.setdefault("client_status", status)
            payload.setdefault("client_last_seen", state.last_seen)
            return payload

    def list_commands(self, device_id: str, limit: int = 50) -> list[Dict[str, Any]]:
        with self._lock:
            history = self._command_history.get(device_id)
            if not history:
                return []
            items = list(history)[-max(1, int(limit)) :]
            return [dict(item) for item in items]

    def enqueue_command(
        self, device_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        command_id = payload.get("id") or uuid.uuid4().hex
        command = {
            "id": command_id,
            "type": payload.get("type"),
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "payload": {
                key: value
                for key, value in payload.items()
                if key not in ("id", "type")
            },
        }
        self.update_command(device_id, command)
        return command

    async def send_to_device(
        self, device_id: str, message: Dict[str, Any]
    ) -> None:
        websocket = self._resolve_socket(device_id)
        try:
            await websocket.send_json(message)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="client send failed: {}".format(exc),
            ) from exc

    async def request_device(
        self,
        device_id: str,
        message: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        websocket = self._resolve_socket(device_id)
        request_id = message.get("request_id") or uuid.uuid4().hex
        message["request_id"] = request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        with self._lock:
            self._pending[request_id] = future
        try:
            await websocket.send_json(message)
            return await asyncio.wait_for(future, timeout=timeout)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="client request failed: {}".format(exc),
            ) from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def resolve_pending(self, request_id: str, payload: Dict[str, Any]) -> bool:
        with self._lock:
            future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(payload)
            return True
        return False

    def sweep(
        self,
        *,
        inactive_after: Optional[float] = None,
        evict_after: Optional[float] = None,
    ) -> list[str]:
        now = time.time()
        to_remove: list[str] = []
        if evict_after is None or evict_after <= 0:
            return to_remove
        with self._lock:
            for client_id, state in list(self._clients.items()):
                reference = state.disconnected_at or state.last_seen
                if now - reference >= evict_after:
                    to_remove.append(client_id)
                    del self._clients[client_id]
            if to_remove:
                self._rebuild_device_index()
        return to_remove

    def _resolve_socket(self, device_id: str) -> WebSocket:
        with self._lock:
            client_id = self._device_index.get(device_id)
            if not client_id:
                raise HTTPException(status_code=404, detail="device not found")
            state = self._clients.get(client_id)
            if not state or not state.connected or not state.websocket:
                raise HTTPException(
                    status_code=404, detail="device not connected"
                )
            return state.websocket

    def _rebuild_device_index(self) -> None:
        self._device_index = {}
        for client_id, state in self._clients.items():
            for device_id in state.devices.keys():
                self._device_index[device_id] = client_id

    @staticmethod
    def _client_status(
        state: ClientState,
        now: float,
        inactive_after: Optional[float],
    ) -> str:
        if not state.connected:
            return "offline"
        if inactive_after is None or inactive_after <= 0:
            return "online"
        if now - state.last_seen >= inactive_after:
            return "offline"
        return "online"
