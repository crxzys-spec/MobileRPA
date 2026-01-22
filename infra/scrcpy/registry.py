import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ScrcpyControlChannel:
    socket: socket.socket
    lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, payload: bytes) -> None:
        with self.lock:
            try:
                if self.socket.fileno() < 0:
                    raise OSError("socket closed")
            except OSError as exc:
                raise OSError("socket closed") from exc
            self.socket.sendall(payload)


_CONTROL_CHANNELS: Dict[str, ScrcpyControlChannel] = {}
_VIDEO_ACTIVE: set[str] = set()
_LOCK = threading.Lock()


def register_control_channel(
    device_id: str, sock: socket.socket
) -> ScrcpyControlChannel:
    with _LOCK:
        existing = _CONTROL_CHANNELS.pop(device_id, None)
        if existing:
            try:
                existing.socket.close()
            except OSError:
                pass
        channel = ScrcpyControlChannel(sock)
        _CONTROL_CHANNELS[device_id] = channel
        return channel


def get_control_channel(device_id: str) -> Optional[ScrcpyControlChannel]:
    with _LOCK:
        channel = _CONTROL_CHANNELS.get(device_id)
        if channel:
            try:
                if channel.socket.fileno() < 0:
                    _CONTROL_CHANNELS.pop(device_id, None)
                    channel = None
            except OSError:
                _CONTROL_CHANNELS.pop(device_id, None)
                channel = None
        return channel


def clear_control_channel(
    device_id: str, expected: Optional[ScrcpyControlChannel] = None
) -> None:
    with _LOCK:
        if expected is not None:
            if _CONTROL_CHANNELS.get(device_id) is not expected:
                return
        channel = _CONTROL_CHANNELS.pop(device_id, None)
    if channel:
        try:
            channel.socket.close()
        except OSError:
            pass


def set_video_active(device_id: str, active: bool) -> None:
    with _LOCK:
        if active:
            _VIDEO_ACTIVE.add(device_id)
        else:
            _VIDEO_ACTIVE.discard(device_id)


def is_video_active(device_id: str) -> bool:
    with _LOCK:
        return device_id in _VIDEO_ACTIVE
