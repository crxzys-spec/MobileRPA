import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from infra.adb import AdbClient


CommandPayload = Dict[str, Any]


@dataclass
class DeviceCommand:
    command_type: str
    payload: CommandPayload
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.command_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "payload": dict(self.payload),
        }


class DeviceSession:
    def __init__(
        self,
        device_id: str,
        adb_path: str,
        ime_id: Optional[str] = None,
        restore_ime: bool = True,
        history_limit: int = 200,
    ) -> None:
        self.device_id = device_id
        self._adb = AdbClient(
            adb_path=adb_path,
            device_id=device_id,
            ime_id=ime_id,
            restore_ime=restore_ime,
        )
        self._queue: "queue.Queue[DeviceCommand]" = queue.Queue()
        self._history: Deque[DeviceCommand] = deque(maxlen=history_limit)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._current_command_id: Optional[str] = None
        self._last_error: Optional[str] = None
        self._created_at = time.time()
        self._updated_at = self._created_at
        self._worker.start()

    def enqueue(self, command: DeviceCommand) -> DeviceCommand:
        with self._lock:
            self._history.append(command)
            self._updated_at = time.time()
        self._queue.put(command)
        return command

    def list_commands(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._history)[-limit:]
        return [item.to_dict() for item in items]

    def get_command(self, command_id: str) -> Optional[DeviceCommand]:
        with self._lock:
            for item in self._history:
                if item.id == command_id:
                    return item
        return None

    def clear_queue(self) -> int:
        drained = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            else:
                drained += 1
                self._queue.task_done()
        if drained:
            with self._lock:
                self._updated_at = time.time()
        return drained

    def stop(self) -> None:
        self._stop_event.set()
        self._worker.join(timeout=2)

    def status_dict(self) -> Dict[str, Any]:
        with self._lock:
            status = "running" if self._current_command_id else "idle"
            return {
                "device_id": self.device_id,
                "status": status,
                "pending": self._queue.qsize(),
                "current_command_id": self._current_command_id,
                "last_error": self._last_error,
                "created_at": self._created_at,
                "updated_at": self._updated_at,
            }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                command = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._execute(command)
            self._queue.task_done()

    def _execute(self, command: DeviceCommand) -> None:
        command.status = "running"
        command.started_at = time.time()
        with self._lock:
            self._current_command_id = command.id
            self._updated_at = command.started_at
        try:
            self._dispatch(command)
            command.status = "done"
        except Exception as exc:
            command.status = "failed"
            command.error = str(exc)
            with self._lock:
                self._last_error = command.error
        finally:
            command.finished_at = time.time()
            with self._lock:
                self._current_command_id = None
                self._updated_at = command.finished_at

    def _dispatch(self, command: DeviceCommand) -> None:
        payload = command.payload
        command_type = command.command_type
        if command_type == "tap":
            self._adb.tap(int(payload["x"]), int(payload["y"]))
            return
        if command_type == "swipe":
            self._adb.swipe(
                int(payload["x1"]),
                int(payload["y1"]),
                int(payload["x2"]),
                int(payload["y2"]),
                int(payload.get("duration_ms", 300)),
            )
            return
        if command_type == "keyevent":
            self._adb.keyevent(payload["keycode"])
            return
        if command_type == "input_text":
            self._adb.input_text(str(payload["text"]))
            return
        if command_type == "start_app":
            package = str(payload["package"])
            activity = payload.get("activity")
            self._adb.start_app(package, activity)
            return
        if command_type == "back":
            self._adb.keyevent(4)
            return
        if command_type == "home":
            self._adb.keyevent(3)
            return
        if command_type == "recent":
            self._adb.keyevent(187)
            return
        if command_type == "wait":
            delay_ms = int(payload.get("wait_ms", 0))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            return
        raise ValueError("unsupported command: {}".format(command_type))


class DeviceSessionManager:
    def __init__(
        self,
        adb_path: str,
        ime_id: Optional[str] = None,
        restore_ime: bool = True,
        history_limit: int = 200,
    ) -> None:
        self._adb_path = adb_path
        self._ime_id = ime_id
        self._restore_ime = restore_ime
        self._history_limit = history_limit
        self._lock = threading.Lock()
        self._sessions: Dict[str, DeviceSession] = {}

    def get_session(self, device_id: str) -> Optional[DeviceSession]:
        with self._lock:
            return self._sessions.get(device_id)

    def get_or_create(self, device_id: str) -> DeviceSession:
        with self._lock:
            session = self._sessions.get(device_id)
            if session is None:
                session = DeviceSession(
                    device_id=device_id,
                    adb_path=self._adb_path,
                    ime_id=self._ime_id,
                    restore_ime=self._restore_ime,
                    history_limit=self._history_limit,
                )
                self._sessions[device_id] = session
            return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [session.status_dict() for session in sessions]

    def enqueue(self, device_id: str, command: DeviceCommand) -> DeviceCommand:
        session = self.get_or_create(device_id)
        return session.enqueue(command)

    def list_commands(self, device_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        session = self.get_session(device_id)
        if not session:
            return []
        return session.list_commands(limit=limit)

    def get_command(self, device_id: str, command_id: str) -> Optional[DeviceCommand]:
        session = self.get_session(device_id)
        if not session:
            return None
        return session.get_command(command_id)

    def clear_queue(self, device_id: str) -> int:
        session = self.get_session(device_id)
        if not session:
            return 0
        return session.clear_queue()

    def close(self, device_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(device_id, None)
        if not session:
            return False
        session.stop()
        return True

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()
