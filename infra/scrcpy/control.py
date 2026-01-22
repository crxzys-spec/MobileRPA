import random
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .registry import (
    ScrcpyControlChannel,
    clear_control_channel,
    get_control_channel,
    is_video_active,
)

CONTROL_MSG_TYPE_INJECT_KEYCODE = 0
CONTROL_MSG_TYPE_INJECT_TEXT = 1
CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT = 2
CONTROL_MSG_TYPE_SET_CLIPBOARD = 9

ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2
ACTION_CANCEL = 3

BUTTON_PRIMARY = 0
INJECT_TEXT_MAX_BYTES = 300
CLIPBOARD_TEXT_MAX_BYTES = 4000


class ScrcpyControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScrcpyControlConfig:
    adb_path: str
    server_path: str
    server_version: str
    log_level: str = ""
    port: int = 0
    connect_timeout: int = 6
    start_delay_ms: int = 200


def _parse_screen_size(output: str) -> Optional[Tuple[int, int]]:
    override = None
    physical = None
    for label, width, height in re.findall(
        r"(Physical|Override) size:\s*(\d+)x(\d+)", output
    ):
        if label.lower() == "override":
            override = (int(width), int(height))
        elif physical is None:
            physical = (int(width), int(height))
    return override or physical


def _adb_screen_size(adb_path: str, device_id: str) -> Tuple[int, int]:
    result = subprocess.run(
        [adb_path, "-s", device_id, "shell", "wm", "size"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ScrcpyControlError(
            "adb wm size failed: {}".format(result.stderr.strip())
        )
    parsed = _parse_screen_size(result.stdout or "")
    if not parsed:
        raise ScrcpyControlError("could not read screen size")
    return parsed


def _scrcpy_server_scid() -> str:
    value = random.randint(1, 0x7FFFFFFF)
    return "{:x}".format(value)


def _scrcpy_allocate_port(preferred: int) -> int:
    if preferred and preferred > 0:
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _scrcpy_available(server_path: str) -> bool:
    if not server_path:
        return False
    if Path(server_path).exists():
        return True
    return shutil.which(server_path) is not None


def _iter_text_chunks(text: str, max_bytes: int):
    buf = []
    size = 0
    for ch in text:
        encoded = ch.encode("utf-8")
        if size + len(encoded) > max_bytes and buf:
            yield "".join(buf)
            buf = [ch]
            size = len(encoded)
        else:
            buf.append(ch)
            size += len(encoded)
    if buf:
        yield "".join(buf)


class ScrcpyControlSession:
    def __init__(self, device_id: str, config: ScrcpyControlConfig) -> None:
        self._device_id = device_id
        self._config = config
        self._lock = threading.Lock()
        self._socket: Optional[socket.socket] = None
        self._channel: Optional[ScrcpyControlChannel] = None
        self._owns_socket = False
        self._process: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._scid: Optional[str] = None
        self._screen_size: Optional[Tuple[int, int]] = None
        self._closed = False
        self._logged_send = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._reset_locked(clear_shared=False)

    def ensure_connected(self) -> None:
        with self._lock:
            if self._closed:
                raise ScrcpyControlError("session closed")
            self._ensure_connected()

    def touch_down(
        self,
        x: int,
        y: int,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> None:
        self._send_touch(ACTION_DOWN, x, y, screen_width, screen_height)

    def touch_move(
        self,
        x: int,
        y: int,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> None:
        self._send_touch(ACTION_MOVE, x, y, screen_width, screen_height)

    def touch_up(
        self,
        x: int,
        y: int,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> None:
        self._send_touch(ACTION_UP, x, y, screen_width, screen_height)

    def keyevent(self, keycode: int) -> None:
        self._send_keyevent(ACTION_DOWN, keycode)
        self._send_keyevent(ACTION_UP, keycode)

    def inject_text(self, text: str) -> None:
        if text is None:
            return
        text = str(text)
        if not text:
            return
        if not text.isascii():
            self.set_clipboard(text, paste=True)
            return
        for chunk in _iter_text_chunks(text, INJECT_TEXT_MAX_BYTES):
            payload = chunk.encode("utf-8")
            message = struct.pack(
                ">BI",
                CONTROL_MSG_TYPE_INJECT_TEXT,
                len(payload),
            ) + payload
            self._send(message)

    def set_clipboard(self, text: str, paste: bool = False) -> None:
        if text is None:
            return
        text = str(text)
        if not text:
            return
        for chunk in _iter_text_chunks(text, CLIPBOARD_TEXT_MAX_BYTES):
            payload = chunk.encode("utf-8")
            sequence = random.getrandbits(64)
            message = struct.pack(
                ">BQBI",
                CONTROL_MSG_TYPE_SET_CLIPBOARD,
                sequence,
                1 if paste else 0,
                len(payload),
            ) + payload
            self._send(message)

    def _send_keyevent(self, action: int, keycode: int) -> None:
        repeat = 0
        meta_state = 0
        message = struct.pack(
            ">BBiii",
            CONTROL_MSG_TYPE_INJECT_KEYCODE,
            action,
            int(keycode),
            repeat,
            meta_state,
        )
        self._send(message)

    def _send_touch(
        self,
        action: int,
        x: int,
        y: int,
        screen_width: Optional[int],
        screen_height: Optional[int],
    ) -> None:
        width, height = self._resolve_screen_size(
            screen_width, screen_height
        )
        pressure = 0xFFFF if action in (ACTION_DOWN, ACTION_MOVE) else 0
        # Touch input should not set mouse button flags for scrcpy control.
        buttons = BUTTON_PRIMARY
        action_button = 0
        message = struct.pack(
            ">BBQiiHHHII",
            CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
            action,
            0,
            int(x),
            int(y),
            int(width),
            int(height),
            pressure,
            action_button,
            buttons,
        )
        self._send(message)

    def _resolve_screen_size(
        self,
        width: Optional[int],
        height: Optional[int],
    ) -> Tuple[int, int]:
        if width and height:
            return int(width), int(height)
        if self._screen_size is None:
            self._screen_size = _adb_screen_size(
                self._config.adb_path, self._device_id
            )
        return self._screen_size

    def _send(self, payload: bytes) -> None:
        with self._lock:
            if self._closed:
                raise ScrcpyControlError("session closed")
            self._ensure_connected()
            channel = self._channel
            if not self._socket:
                raise ScrcpyControlError("control socket unavailable")
            try:
                if self._config.log_level and not self._logged_send:
                    print(
                        "[scrcpy]",
                        self._device_id,
                        "control send",
                        len(payload),
                        payload[:24].hex(),
                        flush=True,
                    )
                    self._logged_send = True
                if channel:
                    channel.send(payload)
                else:
                    self._socket.sendall(payload)
            except OSError as exc:
                if self._config.log_level:
                    print(
                        "[scrcpy]",
                        self._device_id,
                        "control send failed",
                        len(payload),
                        payload[:24].hex(),
                        flush=True,
                    )
                self._reset_locked(clear_shared=self._owns_socket)
                raise ScrcpyControlError(str(exc)) from exc

    def _ensure_connected(self) -> None:
        channel = get_control_channel(self._device_id)
        if channel and _socket_closed(channel.socket):
            clear_control_channel(self._device_id, channel)
            channel = None
        if channel and channel is not self._channel:
            self._socket = channel.socket
            self._channel = channel
            self._owns_socket = False
            return
        if self._socket and not _socket_closed(self._socket):
            return
        self._socket = None
        self._channel = None
        self._owns_socket = False
        deadline = time.time() + max(0.1, self._config.connect_timeout)
        while time.time() < deadline:
            channel = get_control_channel(self._device_id)
            if channel and not _socket_closed(channel.socket):
                self._socket = channel.socket
                self._channel = channel
                self._owns_socket = False
                return
            time.sleep(0.05)
        raise ScrcpyControlError("scrcpy control not ready")

    def _reset_locked(self, clear_shared: bool) -> None:
        if self._socket:
            if self._owns_socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
            self._socket = None
        if self._channel and clear_shared:
            clear_control_channel(self._device_id, self._channel)
        self._channel = None
        self._owns_socket = False
        if self._process:
            _terminate_process(self._process)
            self._process = None
        if self._port is not None:
            _scrcpy_forward_remove(
                self._config.adb_path, self._device_id, self._port
            )
            self._port = None
        self._scid = None


def _socket_closed(sock: socket.socket) -> bool:
    try:
        return sock.fileno() < 0
    except OSError:
        return True


def _build_scrcpy_server_cmd(
    config: ScrcpyControlConfig, device_id: str, scid: str
) -> list[str]:
    cmd = [
        config.adb_path,
        "-s",
        device_id,
        "shell",
        "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
        "app_process",
        "/",
        "com.genymobile.scrcpy.Server",
        config.server_version,
        "scid={}".format(scid),
        *(["log_level={}".format(config.log_level)] if config.log_level else []),
        "tunnel_forward=true",
        "video=false",
        "audio=false",
        "control=true",
        "cleanup=false",
        "send_device_meta=false",
        "send_dummy_byte=false",
    ]
    return cmd


def _scrcpy_push_server(
    adb_path: str, device_id: str, server_path: str
) -> None:
    result = subprocess.run(
        [adb_path, "-s", device_id, "push", server_path, "/data/local/tmp/scrcpy-server.jar"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise ScrcpyControlError(
            "adb push scrcpy-server failed: {}".format(message)
        )


def _scrcpy_forward(
    adb_path: str, device_id: str, port: int, scid: str
) -> None:
    result = subprocess.run(
        [
            adb_path,
            "-s",
            device_id,
            "forward",
            "tcp:{}".format(port),
            "localabstract:scrcpy_{}".format(scid),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ScrcpyControlError(
            "adb forward failed: {}".format(result.stderr.strip())
        )


def _scrcpy_forward_remove(
    adb_path: str, device_id: str, port: int
) -> None:
    subprocess.run(
        [adb_path, "-s", device_id, "forward", "--remove", "tcp:{}".format(port)],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _scrcpy_log_reader(device_id: str, process: subprocess.Popen) -> None:
    if not process.stdout:
        return
    for line in process.stdout:
        print("[scrcpy]", device_id, line.rstrip(), flush=True)


def _scrcpy_connect_socket(port: int, timeout: int) -> socket.socket:
    deadline = time.time() + max(1, timeout)
    last_error = None
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(max(1, timeout))
            return sock
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise ScrcpyControlError("scrcpy connect failed: {}".format(last_error))


def _terminate_process(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
