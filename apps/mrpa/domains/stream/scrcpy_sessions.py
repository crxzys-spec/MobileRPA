import asyncio
import json
import fractions
import queue
import select
import socket
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional

from aiortc import MediaStreamTrack
from av import AudioFrame, Packet

from . import service as stream_service
from infra.scrcpy.registry import (
    clear_control_channel,
    register_control_channel,
    set_video_active,
)


_STOP = object()
_AUDIO_SAMPLE_RATE = 48000
_AUDIO_CHANNELS = 2
_AUDIO_SAMPLE_FORMAT = "s16"
_AUDIO_TIME_BASE = fractions.Fraction(1, _AUDIO_SAMPLE_RATE)
_AUDIO_FRAME_SAMPLES = 960
_AUDIO_FRAME_BYTES = _AUDIO_FRAME_SAMPLES * _AUDIO_CHANNELS * 2


@dataclass
class ScrcpySessionConfig:
    video: bool = True
    audio: bool = False
    control: bool = True
    max_fps: int = stream_service.STREAM_FPS
    video_bit_rate: int = stream_service.STREAM_BITRATE
    max_size: int = stream_service.STREAM_SCALE
    video_codec_options: str = stream_service.SCRCPY_VIDEO_OPTIONS
    audio_codec: str = stream_service.SCRCPY_AUDIO_CODEC
    log_level: str = stream_service.SCRCPY_LOG_LEVEL

    def as_dict(self) -> dict:
        return {
            "video": bool(self.video),
            "audio": bool(self.audio),
            "control": bool(self.control),
            "max_fps": int(self.max_fps),
            "video_bit_rate": int(self.video_bit_rate),
            "max_size": int(self.max_size),
            "video_codec_options": str(self.video_codec_options or ""),
            "audio_codec": str(self.audio_codec or ""),
            "log_level": str(self.log_level or ""),
        }


@dataclass
class ScrcpySessionStatus:
    device_id: str
    status: str
    config: ScrcpySessionConfig
    started_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None
    port: Optional[int] = None
    scid: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "status": self.status,
            "config": self.config.as_dict(),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "port": self.port,
            "scid": self.scid,
        }


class ScrcpySessionTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, session: "ScrcpySession") -> None:
        super().__init__()
        self._session = session
        self._need_keyframe = True

    async def recv(self) -> Packet:
        while True:
            packet = await asyncio.to_thread(self._session.get_packet)
            if self._need_keyframe and not getattr(packet, "is_keyframe", False):
                continue
            self._need_keyframe = False
            return packet


class ScrcpySessionAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, session: "ScrcpySession") -> None:
        super().__init__()
        self._session = session

    async def recv(self) -> Packet:
        while True:
            packet = await asyncio.to_thread(self._session.get_audio_packet)
            return packet


class ScrcpySession:
    def __init__(self, device_id: str, config: ScrcpySessionConfig) -> None:
        self.device_id = device_id
        self._config = config
        self._lock = threading.Lock()
        self._process = None
        self._port: Optional[int] = None
        self._scid: Optional[str] = None
        self._video_socket = None
        self._audio_socket = None
        self._audio_thread: Optional[threading.Thread] = None
        self._audio_queue: "queue.Queue[object]" = queue.Queue(maxsize=128)
        self._audio_codec: Optional[str] = None
        self._audio_pts: Optional[int] = None
        self._control_socket = None
        self._control_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=2)
        self._time_base = fractions.Fraction(1, 1_000_000)
        self._length_size: Optional[int] = None
        self._running = False
        self._starting = False
        self._last_error: Optional[str] = None
        self._started_at: Optional[float] = None
        self._updated_at = time.time()
        self._profile: Optional[str] = None
        self._profile_event = threading.Event()

    def config(self) -> ScrcpySessionConfig:
        return self._config

    def status(self) -> ScrcpySessionStatus:
        with self._lock:
            status = "running" if self._running else "stopped"
            if self._starting and not self._running:
                status = "starting"
            if self._last_error and not self._running and not self._starting:
                status = "error"
            return ScrcpySessionStatus(
                device_id=self.device_id,
                status=status,
                config=self._config,
                started_at=self._started_at,
                updated_at=self._updated_at,
                last_error=self._last_error,
                port=self._port,
                scid=self._scid,
            )

    def start(self) -> ScrcpySessionStatus:
        with self._lock:
            if self._running:
                return self.status()
            if self._starting:
                return self.status()
            if (
                not self._config.video
                and not self._config.audio
                and not self._config.control
            ):
                raise RuntimeError("scrcpy session has no streams enabled")
            self._stop_event.clear()
            self._last_error = None
            self._profile = None
            self._profile_event.clear()
            self._audio_pts = None
            self._starting = True
        stream_service._SCRCPY_PROFILE_CACHE.pop(self.device_id, None)
        try:
            self._start_server()
            self._start_reader()
            with self._lock:
                self._running = True
                self._starting = False
                self._updated_at = time.time()
            return self.status()
        except Exception as exc:
            self._set_error(str(exc))
            self.stop()
            return self.status()

    def stop(self) -> ScrcpySessionStatus:
        with self._lock:
            if not self._running and not self._process and not self._starting:
                return self.status()
            self._stop_event.set()
            self._running = False
            self._starting = False
            self._updated_at = time.time()
            self._profile_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1)
        if self._audio_thread and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=1)
        if self._control_thread and self._control_thread.is_alive():
            self._control_thread.join(timeout=1)
        self._shutdown()
        return self.status()

    def restart(self, config: Optional[ScrcpySessionConfig] = None) -> ScrcpySessionStatus:
        if config:
            self._config = config
        self.stop()
        return self.start()

    def get_packet(self) -> Packet:
        item = self._queue.get()
        if item is _STOP:
            raise RuntimeError("scrcpy session stopped")
        return item

    def get_audio_packet(self) -> Packet:
        item = self._audio_queue.get()
        if item is _STOP:
            raise RuntimeError("scrcpy session stopped")
        return item

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
            self._updated_at = time.time()
        self._profile_event.set()

    def _set_profile(self, profile: Optional[str]) -> None:
        if not profile:
            return
        with self._lock:
            if self._profile == profile:
                return
            self._profile = profile
            self._updated_at = time.time()
        self._profile_event.set()

    def wait_for_profile(self, timeout: float) -> Optional[str]:
        if self._profile:
            return self._profile
        self._profile_event.wait(timeout)
        return self._profile

    def _start_server(self) -> None:
        stream_service._require_binary(stream_service.ADB_PATH, "adb")
        stream_service._require_binary(
            stream_service.SCRCPY_SERVER_PATH, "scrcpy-server"
        )
        stream_service._scrcpy_push_server(self.device_id)
        scid = stream_service._scrcpy_server_scid()
        port = stream_service._scrcpy_allocate_port()
        stream_service._scrcpy_forward_remove(self.device_id, port)
        stream_service._scrcpy_forward(self.device_id, port, scid)
        cmd = _build_server_cmd(self.device_id, scid, self._config)
        if self._config.log_level:
            process = stream_service.subprocess.Popen(
                cmd,
                stdout=stream_service.subprocess.PIPE,
                stderr=stream_service.subprocess.STDOUT,
                text=True,
            )
            threading.Thread(
                target=stream_service._scrcpy_log_reader,
                args=(self.device_id, process),
                daemon=True,
            ).start()
            print(
                "[scrcpy] cmd",
                self.device_id,
                " ".join(cmd),
                flush=True,
            )
        else:
            process = stream_service.subprocess.Popen(
                cmd,
                stdout=stream_service.subprocess.DEVNULL,
                stderr=stream_service.subprocess.DEVNULL,
            )
        if stream_service.SCRCPY_START_DELAY_MS > 0:
            time.sleep(stream_service.SCRCPY_START_DELAY_MS / 1000.0)
        self._process = process
        self._port = port
        self._scid = scid
        self._started_at = time.time()
        self._updated_at = self._started_at
        if not stream_service._scrcpy_wait_for_socket(
            self.device_id, scid, stream_service.SCRCPY_CONNECT_TIMEOUT
        ):
            exit_code = None
            if self._process:
                exit_code = self._process.poll()
            if self._config.log_level:
                print(
                    "[scrcpy]",
                    self.device_id,
                    "socket not ready",
                    "exit",
                    exit_code,
                    flush=True,
                )
            raise RuntimeError("scrcpy socket not ready")

    def _start_reader(self) -> None:
        if (
            not self._config.video
            and not self._config.audio
            and not self._config.control
        ):
            return
        self._reader_thread = threading.Thread(
            target=self._reader, daemon=True
        )
        self._reader_thread.start()

    def _reader(self) -> None:
        if (
            not self._config.video
            and not self._config.audio
            and not self._config.control
        ):
            return
        port = self._port
        if not port:
            return
        video_sock = None
        audio_sock = None
        control_sock = None
        meta_timeout = stream_service.SCRCPY_READ_TIMEOUT * max(
            1, stream_service.SCRCPY_META_RETRIES
        )
        try:
            if self._config.video:
                video_sock = stream_service._scrcpy_connect_socket(
                    port, stream_service.SCRCPY_CONNECT_TIMEOUT
                )
            if self._config.audio:
                audio_sock = stream_service._scrcpy_connect_socket(
                    port, stream_service.SCRCPY_CONNECT_TIMEOUT
                )
            if self._config.control:
                control_sock = stream_service._scrcpy_connect_socket(
                    port, stream_service.SCRCPY_CONNECT_TIMEOUT
                )
        except Exception as exc:
            self._set_error("scrcpy connect failed: {}".format(exc))
        if self._stop_event.is_set():
            for sock in (video_sock, audio_sock, control_sock):
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if not self._last_error:
                self._set_error("scrcpy socket closed")
            self._stop_event.set()
            self._shutdown()
            self._queue.put(_STOP)
            self._audio_queue.put(_STOP)
            with self._lock:
                self._running = False
                self._starting = False
                self._updated_at = time.time()
            return
        if self._config.video and not video_sock:
            self._set_error("scrcpy video socket missing")
        if self._config.audio and not audio_sock:
            self._set_error("scrcpy audio socket missing")
        if self._config.control and not control_sock:
            self._set_error("scrcpy control socket missing")
        if self._last_error:
            self._stop_event.set()
            self._shutdown()
            self._queue.put(_STOP)
            self._audio_queue.put(_STOP)
            with self._lock:
                self._running = False
                self._starting = False
                self._updated_at = time.time()
            return
        self._video_socket = video_sock
        self._audio_socket = audio_sock
        self._control_socket = control_sock
        if self._control_socket:
            try:
                self._control_socket.settimeout(None)
            except OSError:
                pass
            register_control_channel(self.device_id, self._control_socket)
            if not self._config.video:
                set_video_active(self.device_id, True)
            self._control_thread = threading.Thread(
                target=_drain_control,
                args=(
                    self.device_id,
                    self._control_socket,
                    self._stop_event,
                    self._config.log_level,
                ),
                daemon=True,
            )
            self._control_thread.start()
        if self._audio_socket:
            try:
                codec = _read_audio_meta(self._audio_socket, meta_timeout)
            except Exception:
                codec = None
            if not codec:
                self._set_error("scrcpy audio meta missing")
            else:
                self._audio_codec = codec
                if codec not in ("opus", "raw"):
                    self._set_error("scrcpy unsupported audio codec {}".format(codec))
            if self._last_error:
                self._stop_event.set()
                self._shutdown()
                self._queue.put(_STOP)
                self._audio_queue.put(_STOP)
                with self._lock:
                    self._running = False
                    self._starting = False
                    self._updated_at = time.time()
                return
            self._audio_thread = threading.Thread(
                target=self._audio_reader,
                daemon=True,
            )
            self._audio_thread.start()
        if not self._config.video:
            while not self._stop_event.is_set():
                if self._audio_thread and not self._audio_thread.is_alive():
                    self._set_error("scrcpy audio stream ended")
                    self._stop_event.set()
                    break
                if self._control_thread and not self._control_thread.is_alive():
                    self._set_error("scrcpy control stream ended")
                    self._stop_event.set()
                    break
                time.sleep(0.2)
            self._shutdown()
            self._queue.put(_STOP)
            self._audio_queue.put(_STOP)
            with self._lock:
                self._running = False
                self._starting = False
                self._updated_at = time.time()
            return
        meta = stream_service._scrcpy_read_codec_meta(video_sock, meta_timeout)
        if not meta or self._stop_event.is_set():
            exit_code = None
            if self._process:
                exit_code = self._process.poll()
            if self._config.log_level:
                print(
                    "[scrcpy]",
                    self.device_id,
                    "meta missing",
                    "exit",
                    exit_code,
                    flush=True,
                )
            self._set_error("scrcpy meta missing")
            self._stop_event.set()
            self._shutdown()
            self._queue.put(_STOP)
            self._audio_queue.put(_STOP)
            with self._lock:
                self._running = False
                self._starting = False
                self._updated_at = time.time()
            return
        try:
            video_sock.settimeout(None)
        except OSError:
            pass
        set_video_active(self.device_id, True)
        codec_name, _width, _height, leftover = meta
        buffer = bytearray(leftover)
        if codec_name != "h264":
            self._set_error("scrcpy unsupported codec {}".format(codec_name))
            self._stop_event.set()
            self._shutdown()
            self._queue.put(_STOP)
            self._audio_queue.put(_STOP)
            with self._lock:
                self._running = False
                self._updated_at = time.time()
            return
        sps = None
        pps = None
        pcm_buffer = bytearray()
        while not self._stop_event.is_set():
            header = stream_service._recv_exact_socket_buffered(
                video_sock, 12, buffer
            )
            if not header:
                break
            try:
                config, keyframe, pts, size = (
                    stream_service._parse_scrcpy_frame_header(header)
                )
            except ValueError:
                break
            if size <= 0:
                continue
            raw_payload = stream_service._recv_exact_socket_buffered(
                video_sock, size, buffer
            )
            if not raw_payload:
                break
            if config:
                parsed = stream_service._parse_avc_config_record(raw_payload)
                if parsed:
                    nalus, length_size = parsed
                    self._length_size = length_size
                else:
                    payload = stream_service._ensure_annexb_with_length(
                        raw_payload, self._length_size
                    )
                    nalus = stream_service._split_annexb_nalus(payload)
                for nalu in nalus:
                    nal_type = stream_service._nalu_type_from_annexb(nalu)
                    if nal_type == 7:
                        sps = nalu
                        profile = stream_service._h264_profile_id_from_sps(nalu)
                        if profile:
                            self._set_profile(profile)
                            stream_service._SCRCPY_PROFILE_CACHE[
                                self.device_id
                            ] = profile
                    elif nal_type == 8:
                        pps = nalu
                continue
            payload = stream_service._ensure_annexb_with_length(
                raw_payload, self._length_size
            )
            nalus = stream_service._split_annexb_nalus(payload)
            if not nalus:
                continue
            types = []
            for nalu in nalus:
                nal_type = stream_service._nalu_type_from_annexb(nalu)
                if nal_type is None:
                    continue
                types.append(nal_type)
                if nal_type == 7:
                    sps = nalu
                elif nal_type == 8:
                    pps = nalu
            has_vcl = any(nal_type in (1, 5) for nal_type in types)
            if not has_vcl:
                continue
            is_idr = keyframe or 5 in types
            output_nalus = []
            if is_idr and sps and pps and (7 not in types or 8 not in types):
                output_nalus.extend([sps, pps])
            output_nalus.extend(nalus)
            packet = Packet(b"".join(output_nalus))
            packet.pts = pts
            packet.dts = pts
            packet.time_base = self._time_base
            packet.is_keyframe = bool(is_idr)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(packet)
        if not self._stop_event.is_set():
            self._set_error("scrcpy stream ended")
            self._stop_event.set()
        self._shutdown()
        self._queue.put(_STOP)
        self._audio_queue.put(_STOP)
        with self._lock:
            self._running = False
            self._starting = False
            self._updated_at = time.time()

    def _audio_reader(self) -> None:
        sock = self._audio_socket
        if not sock:
            return
        buffer = bytearray()
        pcm_buffer = bytearray()
        try:
            sock.settimeout(None)
        except OSError:
            pass
        while not self._stop_event.is_set():
            header = stream_service._recv_exact_socket_buffered(
                sock, 12, buffer
            )
            if not header:
                break
            try:
                config, _keyframe, pts, size = (
                    stream_service._parse_scrcpy_frame_header(header)
                )
            except ValueError:
                break
            if size <= 0:
                continue
            payload = stream_service._recv_exact_socket_buffered(
                sock, size, buffer
            )
            if not payload:
                break
            if config:
                continue
            if self._audio_codec == "raw":
                pcm_buffer.extend(payload)
                while len(pcm_buffer) >= _AUDIO_FRAME_BYTES:
                    chunk = bytes(pcm_buffer[:_AUDIO_FRAME_BYTES])
                    del pcm_buffer[:_AUDIO_FRAME_BYTES]
                    pts_samples = self._audio_pts
                    if pts_samples is None:
                        pts_samples = int(
                            pts * _AUDIO_SAMPLE_RATE / 1_000_000
                        )
                    frame = _build_raw_audio_frame(chunk, pts_samples)
                    if not frame:
                        continue
                    self._audio_pts = pts_samples + _AUDIO_FRAME_SAMPLES
                    try:
                        self._audio_queue.put(frame, timeout=0.5)
                    except queue.Full:
                        pass
                continue
            packet = Packet(payload)
            packet.pts = pts
            packet.dts = pts
            packet.time_base = self._time_base
            try:
                self._audio_queue.put(packet, timeout=0.5)
            except queue.Full:
                pass
        if not self._stop_event.is_set():
            self._set_error("scrcpy audio stream ended")
            self._stop_event.set()

    def _shutdown(self) -> None:
        def _close_socket(sock: Optional[socket.socket]) -> None:
            if not sock:
                return
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        if self._video_socket:
            _close_socket(self._video_socket)
            self._video_socket = None
        if self._audio_socket:
            _close_socket(self._audio_socket)
            self._audio_socket = None
        if self._control_socket:
            _close_socket(self._control_socket)
            self._control_socket = None
        clear_control_channel(self.device_id)
        set_video_active(self.device_id, False)
        stream_service._terminate_process(self._process)
        stream_service._scrcpy_forward_remove(self.device_id, self._port)
        self._process = None
        self._port = None
        self._scid = None


class ScrcpySessionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, ScrcpySession] = {}
        self._configs: Dict[str, ScrcpySessionConfig] = {}
        self._config_path = (
            stream_service.OUTPUTS_DIR / "scrcpy_session_configs.json"
        )
        self._load_configs()

    def _load_configs(self) -> None:
        path = self._config_path
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if stream_service.SCRCPY_LOG_LEVEL:
                print("[scrcpy] config load failed", exc, flush=True)
            return
        if not isinstance(raw, dict):
            return
        defaults = ScrcpySessionConfig().as_dict()
        for device_id, data in raw.items():
            if not isinstance(device_id, str) or not isinstance(data, dict):
                continue
            merged = defaults.copy()
            merged.update(data)
            try:
                self._configs[device_id] = ScrcpySessionConfig(**merged)
            except TypeError:
                continue

    def _save_configs(self) -> None:
        path = self._config_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                device_id: config.as_dict()
                for device_id, config in self._configs.items()
            }
            tmp_path = Path(str(path) + ".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError as exc:
            if stream_service.SCRCPY_LOG_LEVEL:
                print("[scrcpy] config save failed", exc, flush=True)

    def list_sessions(self) -> list[ScrcpySessionStatus]:
        with self._lock:
            return [session.status() for session in self._sessions.values()]

    def get_session(self, device_id: str) -> Optional[ScrcpySession]:
        with self._lock:
            return self._sessions.get(device_id)

    def get_config(self, device_id: str) -> ScrcpySessionConfig:
        with self._lock:
            config = self._configs.get(device_id)
        if config:
            return config
        return ScrcpySessionConfig()

    def set_config(self, device_id: str, config: ScrcpySessionConfig) -> None:
        with self._lock:
            self._configs[device_id] = config
            session = self._sessions.get(device_id)
        if session:
            status = session.status().status
            if status not in ("running", "starting"):
                session._config = config
                session._updated_at = time.time()
        self._save_configs()

    def start(
        self, device_id: str, config: Optional[ScrcpySessionConfig] = None
    ) -> ScrcpySessionStatus:
        with self._lock:
            session = self._sessions.get(device_id)
            if session is None:
                session = ScrcpySession(
                    device_id, config or self.get_config(device_id)
                )
                self._sessions[device_id] = session
            if config:
                self._configs[device_id] = config
        if config:
            self._save_configs()
            status = session.status().status
            if status not in ("running", "starting"):
                session._config = config
                session._updated_at = time.time()
        return session.start()

    def stop(self, device_id: str) -> ScrcpySessionStatus:
        with self._lock:
            session = self._sessions.get(device_id)
        if not session:
            return ScrcpySessionStatus(
                device_id=device_id,
                status="stopped",
                config=self.get_config(device_id),
            )
        return session.stop()

    def restart(
        self, device_id: str, config: Optional[ScrcpySessionConfig] = None
    ) -> ScrcpySessionStatus:
        with self._lock:
            session = self._sessions.get(device_id)
            if session is None:
                session = ScrcpySession(
                    device_id, config or self.get_config(device_id)
                )
                self._sessions[device_id] = session
            if config is None:
                config = self.get_config(device_id)
            if config:
                self._configs[device_id] = config
        if config:
            self._save_configs()
        return session.restart(config)

    def create_track(
        self, device_id: str, loop: asyncio.AbstractEventLoop
    ) -> MediaStreamTrack:
        session = self.get_session(device_id)
        if not session:
            raise RuntimeError("scrcpy session not running")
        status = session.status()
        if status.status != "running":
            raise RuntimeError("scrcpy session not running")
        if not status.config.video:
            raise RuntimeError("scrcpy session video disabled")
        return ScrcpySessionTrack(session)

    def create_audio_track(
        self, device_id: str, loop: asyncio.AbstractEventLoop
    ) -> MediaStreamTrack:
        session = self.get_session(device_id)
        if not session:
            raise RuntimeError("scrcpy session not running")
        status = session.status()
        if status.status != "running":
            raise RuntimeError("scrcpy session not running")
        if not status.config.audio:
            raise RuntimeError("scrcpy session audio disabled")
        return ScrcpySessionAudioTrack(session)

    def wait_for_profile(
        self, device_id: str, timeout: float
    ) -> Optional[str]:
        session = self.get_session(device_id)
        if not session:
            return None
        status = session.status()
        if status.status not in ("running", "starting"):
            return None
        return session.wait_for_profile(timeout)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.stop()


def _build_server_cmd(
    device_id: str, scid: str, config: ScrcpySessionConfig
) -> list[str]:
    cmd = [
        stream_service.ADB_PATH,
        "-s",
        device_id,
        "shell",
        "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
        "app_process",
        "/",
        "com.genymobile.scrcpy.Server",
        stream_service.SCRCPY_SERVER_VERSION,
        "scid={}".format(scid),
        *(["log_level={}".format(config.log_level)] if config.log_level else []),
        "tunnel_forward=true",
        "audio={}".format("true" if config.audio else "false"),
        "control={}".format("true" if config.control else "false"),
        "send_device_meta=false",
        "send_dummy_byte=false",
        "send_codec_meta=true",
        "send_frame_meta=true",
        "cleanup=false",
    ]
    if config.video:
        cmd.extend(
            [
                "video_codec=h264",
                "max_fps={}".format(max(1, int(config.max_fps))),
                "video_bit_rate={}".format(
                    max(1, int(config.video_bit_rate))
                ),
            ]
        )
        if config.max_size and int(config.max_size) > 0:
            cmd.append("max_size={}".format(int(config.max_size)))
        if config.video_codec_options:
            cmd.append(
                "video_codec_options={}".format(config.video_codec_options)
            )
    else:
        cmd.append("video=false")
    if config.audio and config.audio_codec:
        cmd.append("audio_codec={}".format(config.audio_codec))
    return cmd


def _decode_audio_codec(raw: bytes) -> str:
    if len(raw) < 4:
        return ""
    try:
        text = (
            raw.decode("ascii", errors="ignore")
            .lower()
            .replace("\x00", "")
            .strip()
        )
    except OSError:
        text = ""
    if text in ("opus", "aac", "raw"):
        return text
    code = int.from_bytes(raw[:4], "big")
    if code == 1:
        return "opus"
    if code == 2:
        return "aac"
    if code == 3:
        return "raw"
    return str(code)


def _read_audio_meta(sock, timeout: float) -> Optional[str]:
    meta = stream_service._recv_exact_socket(sock, 4, timeout)
    if not meta:
        return None
    return _decode_audio_codec(meta)


def _build_raw_audio_frame(
    payload: bytes, pts_samples: int
) -> Optional[AudioFrame]:
    bytes_per_sample = 2
    frame_size = bytes_per_sample * _AUDIO_CHANNELS
    if frame_size <= 0 or len(payload) % frame_size != 0:
        return None
    samples = len(payload) // frame_size
    if samples <= 0:
        return None
    frame = AudioFrame(
        format=_AUDIO_SAMPLE_FORMAT, layout="stereo", samples=samples
    )
    frame.sample_rate = _AUDIO_SAMPLE_RATE
    frame.pts = pts_samples
    frame.time_base = _AUDIO_TIME_BASE
    frame.planes[0].update(payload)
    return frame


def _drain_audio(
    device_id: str,
    sock,
    stop_event: threading.Event,
    log_level: str,
) -> None:
    try:
        sock.settimeout(1)
        while not stop_event.is_set():
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
    finally:
        if log_level:
            print("[scrcpy]", device_id, "audio stream ended", flush=True)


def _drain_control(
    device_id: str,
    sock,
    stop_event: threading.Event,
    log_level: str,
) -> None:
    try:
        while not stop_event.is_set():
            try:
                readable, _, _ = select.select([sock], [], [], 0.5)
                if not readable:
                    continue
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
    finally:
        clear_control_channel(device_id)
        if log_level:
            print("[scrcpy]", device_id, "control stream ended", flush=True)
