import asyncio
import fractions
import json
import os
import re
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from apps.mrpa_studio.settings import StudioSettings
from aiortc import (
    MediaStreamTrack,
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
    RTCSessionDescription,
    RTCRtpSender,
    VideoStreamTrack,
)
from aiortc import sdp as aiortc_sdp
from aiortc.rtcrtpparameters import RTCRtpCodecParameters, RTCRtcpFeedback
import aiortc.codecs as aiortc_codecs
import av
from av import Packet, VideoFrame
import cv2
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT_DIR / "outputs"
STATIC_DIR = Path(__file__).parent / "static"

RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9:._-]+$")

def _resolve_adb_path(configured: Optional[str]) -> str:
    if configured:
        return configured
    adb_name = "adb.exe" if os.name == "nt" else "adb"
    bundled = ROOT_DIR / "tools" / "platform-tools" / adb_name
    if bundled.exists():
        return str(bundled)
    return "adb"


def _resolve_ffmpeg_path(configured: Optional[str]) -> str:
    if configured:
        return configured
    ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled_root = ROOT_DIR / "tools" / "ffmpeg"
    direct = bundled_root / ffmpeg_name
    if direct.exists():
        return str(direct)
    bin_path = bundled_root / "bin" / ffmpeg_name
    if bin_path.exists():
        return str(bin_path)
    for candidate in bundled_root.glob("*/bin/{}".format(ffmpeg_name)):
        if candidate.exists():
            return str(candidate)
    return "ffmpeg"


def _resolve_scrcpy_path(configured: Optional[str]) -> str:
    if configured:
        return configured
    scrcpy_name = "scrcpy.exe" if os.name == "nt" else "scrcpy"
    bundled_root = ROOT_DIR / "tools" / "scrcpy"
    direct = bundled_root / scrcpy_name
    if direct.exists():
        return str(direct)
    for candidate in bundled_root.glob("**/{}".format(scrcpy_name)):
        if candidate.exists():
            return str(candidate)
    return "scrcpy"


def _resolve_scrcpy_server_path(
    scrcpy_path: str, configured: Optional[str]
) -> str:
    if configured:
        return configured
    bundled_root = ROOT_DIR / "tools" / "scrcpy"
    for name in ("scrcpy-server", "scrcpy-server.jar", "scrcpy-server.apk"):
        candidate = bundled_root / name
        if candidate.exists():
            return str(candidate)
    scrcpy_dir = Path(scrcpy_path).parent
    for name in ("scrcpy-server", "scrcpy-server.jar", "scrcpy-server.apk"):
        candidate = scrcpy_dir / name
        if candidate.exists():
            return str(candidate)
    return "scrcpy-server"


SETTINGS = StudioSettings()

ADB_PATH = _resolve_adb_path(SETTINGS.adb_path)
FFMPEG_PATH = _resolve_ffmpeg_path(SETTINGS.ffmpeg_path)
SCRCPY_PATH = _resolve_scrcpy_path(SETTINGS.scrcpy_path)
SCRCPY_SERVER_PATH = _resolve_scrcpy_server_path(
    SCRCPY_PATH, SETTINGS.scrcpy_server_path
)
STREAM_FPS = SETTINGS.stream_fps
STREAM_SCALE = SETTINGS.stream_scale
STREAM_BITRATE = SETTINGS.stream_bitrate
STREAM_QUALITY = SETTINGS.stream_quality
STREAM_SEGMENT_SECONDS = SETTINGS.stream_segment_seconds
STREAM_ANALYZE_US = SETTINGS.stream_analyze_us
STREAM_PROBESIZE = SETTINGS.stream_probesize
STREAM_DRIVER = SETTINGS.stream_driver
STREAM_DETECTION_TIMEOUT = SETTINGS.stream_detection_timeout
STREAM_SCRCPY_FORMAT = "mkv"
WEBRTC_SOURCE = SETTINGS.webrtc_source
SCRCPY_SERVER_VERSION = SETTINGS.scrcpy_server_version
SCRCPY_SERVER_PORT = SETTINGS.scrcpy_server_port
SCRCPY_CONNECT_TIMEOUT = SETTINGS.scrcpy_connect_timeout
SCRCPY_READ_TIMEOUT = SETTINGS.scrcpy_read_timeout
SCRCPY_META_RETRIES = SETTINGS.scrcpy_meta_retries
SCRCPY_START_DELAY_MS = SETTINGS.scrcpy_start_delay_ms
SCRCPY_VIDEO_OPTIONS = SETTINGS.scrcpy_video_options
SCRCPY_LOG_LEVEL = SETTINGS.scrcpy_log_level
WEBRTC_ICE_URLS = SETTINGS.webrtc_ice_urls
SCRCPY_CODEC_NAMES = {1: "h264", 2: "h265", 3: "av1"}
FORCED_H264_PROFILE = SETTINGS.forced_h264_profile

_SCREENRECORD_CAPS: Dict[str, bool] = {}
_SCREEN_SIZE_CACHE: Dict[str, Tuple[int, int]] = {}
_H264_PROFILE_CACHE: Dict[str, str] = {}
_SCRCPY_PROFILE_CACHE: Dict[str, str] = {}


class RunRequest(BaseModel):
    goal: str = Field(min_length=1)
    device: Optional[str] = None
    execute: bool = True
    plan: bool = True
    plan_max_steps: int = 5
    plan_verify: str = "llm"
    plan_resume: bool = True
    max_steps: int = 5
    max_actions: int = 5
    skills: bool = False
    skills_only: bool = False
    text_only: bool = False
    decision_mode: Optional[str] = None


class WebRTCOffer(BaseModel):
    sdp: str
    type: str
    device_id: str = Field(min_length=1)


class RunManager:
    def __init__(self, outputs_dir: Path) -> None:
        self._outputs_dir = outputs_dir
        self._lock = threading.Lock()
        self._processes: Dict[str, subprocess.Popen] = {}

    def start_run(self, request: RunRequest) -> Dict[str, object]:
        run_id = self._new_run_id()
        run_dir = self._outputs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        output_path = run_dir / "result.json"
        log_path = run_dir / "run.log"

        cmd = self._build_command(request, run_dir, output_path)
        metadata = {
            "id": run_id,
            "goal": request.goal,
            "device_id": request.device,
            "status": "running",
            "start_time": time.time(),
            "command": cmd,
            "trace_dir": str(run_dir),
            "output_path": str(output_path),
            "log_path": str(log_path),
        }
        self._write_run_metadata(run_dir, metadata)

        log_file = open(log_path, "w", encoding="utf-8")
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=log_file,
            text=True,
        )
        metadata["pid"] = process.pid
        self._write_run_metadata(run_dir, metadata)
        with self._lock:
            self._processes[run_id] = process
        thread = threading.Thread(
            target=self._watch_run,
            args=(run_id, run_dir, process, log_file),
            daemon=True,
        )
        thread.start()
        return metadata

    def stop_run(self, run_id: str) -> Dict[str, object]:
        run_id = _validate_run_id(run_id)
        with self._lock:
            process = self._processes.get(run_id)
        run_dir = self._outputs_dir / run_id
        metadata = _read_json(run_dir / "run.json") or {"id": run_id}
        if not process:
            pid = metadata.get("pid")
            if not pid:
                pid = _find_pid_by_hint(run_id)
            if not pid:
                raise HTTPException(status_code=404, detail="run not active")
            _terminate_pid(pid)
            metadata["pid"] = pid
        else:
            _terminate_process(process)
            metadata["pid"] = process.pid
        metadata["status"] = "stopping"
        metadata["stop_requested"] = time.time()
        self._write_run_metadata(run_dir, metadata)
        return {"id": run_id, "status": "stopping"}

    def list_runs(self) -> List[Dict[str, object]]:
        if not self._outputs_dir.exists():
            return []
        runs = []
        for item in sorted(self._outputs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not item.is_dir():
                continue
            run_id = item.name
            if not RUN_ID_RE.match(run_id):
                continue
            metadata = _read_json(item / "run.json") or {}
            metadata.setdefault("id", run_id)
            metadata.setdefault("trace_dir", str(item))
            metadata["updated_time"] = item.stat().st_mtime
            with self._lock:
                process = self._processes.get(run_id)
            dirty = False
            if process and metadata.get("status") == "running":
                metadata["pid"] = process.pid
                dirty = True
            pid = metadata.get("pid")
            status = (metadata.get("status") or "").lower()
            if pid and status in ("running", "stopping") and not _is_pid_running(pid):
                metadata["status"] = "stopped"
                metadata.setdefault("end_time", time.time())
                metadata.setdefault("exit_code", -1)
                dirty = True
            if dirty:
                self._write_run_metadata(item, metadata)
            runs.append(metadata)
        return runs

    def _build_command(self, request: RunRequest, run_dir: Path, output_path: Path) -> List[str]:
        cmd = [
            sys.executable,
            str(ROOT_DIR / "bot.py"),
            "agent",
            "--goal",
            request.goal,
            "--max-steps",
            str(request.max_steps),
            "--max-actions",
            str(request.max_actions),
            "--trace-dir",
            str(run_dir),
            "--output",
            str(output_path),
        ]
        if request.device:
            cmd.extend(["--device", request.device])
        if request.execute:
            cmd.append("--execute")
        if request.text_only:
            cmd.append("--text-only")
        if request.decision_mode:
            cmd.extend(["--decision-mode", request.decision_mode])
        if request.plan:
            cmd.append("--plan")
        cmd.extend(["--plan-max-steps", str(request.plan_max_steps)])
        cmd.extend(["--plan-verify", request.plan_verify])
        if not request.plan_resume:
            cmd.append("--no-plan-resume")
        if request.skills:
            cmd.append("--skills")
        if request.skills_only:
            cmd.append("--skills-only")
        return cmd

    def _new_run_id(self) -> str:
        base = time.strftime("run_%Y%m%d_%H%M%S")
        run_id = base
        index = 1
        while (self._outputs_dir / run_id).exists():
            index += 1
            run_id = "{}_{}".format(base, index)
        return run_id

    def _write_run_metadata(self, run_dir: Path, metadata: Dict[str, object]) -> None:
        (run_dir / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _watch_run(
        self,
        run_id: str,
        run_dir: Path,
        process: subprocess.Popen,
        log_file,
    ) -> None:
        exit_code = process.wait()
        log_file.close()
        metadata = _read_json(run_dir / "run.json") or {}
        metadata["end_time"] = time.time()
        metadata["exit_code"] = exit_code
        metadata["status"] = "finished" if exit_code == 0 else "failed"
        self._write_run_metadata(run_dir, metadata)
        with self._lock:
            self._processes.pop(run_id, None)


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    return run_id


def _validate_device_id(device_id: str) -> str:
    if not device_id or not DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=400, detail="invalid device id")
    return device_id


def _is_pid_running(pid: int) -> bool:
    if pid is None:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", "PID eq {}".format(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        output = result.stdout or ""
        return re.search(r"\b{}\b".format(pid), output) is not None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int) -> None:
    if pid is None:
        return
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return


def _find_pid_by_hint(hint: str) -> Optional[int]:
    if os.name != "nt":
        return None
    if not hint:
        return None
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*" + hint + "*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return int(line)
        except ValueError:
            continue
    return None


def _read_json(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _require_binary(path: str, label: str) -> None:
    if Path(path).exists():
        return
    if shutil.which(path) is None:
        raise HTTPException(
            status_code=500, detail="{} not found: {}".format(label, path)
        )


def _list_adb_devices() -> List[Dict[str, str]]:
    _require_binary(ADB_PATH, "adb")
    result = subprocess.run(
        [ADB_PATH, "devices"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail="adb devices failed: {}".format(result.stderr.strip()),
        )
    devices = []
    lines = (result.stdout or "").splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"id": parts[0], "status": parts[1]})
    return devices


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
    if override:
        return override
    if physical:
        return physical
    match = re.search(r"(\d+)x(\d+)", output)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _adb_screen_size(device_id: str) -> Tuple[int, int]:
    cached = _SCREEN_SIZE_CACHE.get(device_id)
    if cached:
        return cached
    _require_binary(ADB_PATH, "adb")
    result = subprocess.run(
        [ADB_PATH, "-s", device_id, "shell", "wm", "size"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail="adb wm size failed: {}".format(result.stderr.strip()),
        )
    parsed = _parse_screen_size(result.stdout or "")
    if not parsed:
        raise HTTPException(status_code=500, detail="could not read screen size")
    _SCREEN_SIZE_CACHE[device_id] = parsed
    return parsed


def _scaled_dimensions(width: int, height: int) -> Tuple[int, int]:
    if STREAM_SCALE <= 0 or height <= STREAM_SCALE:
        return width, height
    scale = STREAM_SCALE / float(height)
    target_width = max(2, int(width * scale))
    target_height = max(2, int(height * scale))
    if target_width % 2:
        target_width -= 1
    if target_height % 2:
        target_height -= 1
    return max(2, target_width), max(2, target_height)


def _screenrecord_supports_raw(device_id: str) -> bool:
    cached = _SCREENRECORD_CAPS.get(device_id)
    if cached is not None:
        return cached
    _require_binary(ADB_PATH, "adb")
    result = subprocess.run(
        [
            ADB_PATH,
            "-s",
            device_id,
            "exec-out",
            "screenrecord",
            "--output-format=h264",
            "--time-limit",
            "1",
            "-",
        ],
        capture_output=True,
        timeout=STREAM_DETECTION_TIMEOUT,
    )
    if result.returncode != 0:
        _SCREENRECORD_CAPS[device_id] = False
        return False
    payload = result.stdout or b""
    if not payload:
        _SCREENRECORD_CAPS[device_id] = False
        return False
    head = payload[:2048]
    text = head.decode("utf-8", errors="ignore").lower()
    err_text = (result.stderr or b"").decode("utf-8", errors="ignore").lower()
    if "unknown option" in text or "unknown option" in err_text:
        _SCREENRECORD_CAPS[device_id] = False
        return False
    if "usage:" in text or "usage:" in err_text:
        _SCREENRECORD_CAPS[device_id] = False
        return False
    if b"ftyp" in head:
        _SCREENRECORD_CAPS[device_id] = False
        return False
    if b"\x00\x00\x00\x01" in head or b"\x00\x00\x01" in head:
        _SCREENRECORD_CAPS[device_id] = True
        return True
    _SCREENRECORD_CAPS[device_id] = False
    return False


def _screencap_bytes(device_id: str) -> Optional[bytes]:
    _require_binary(ADB_PATH, "adb")
    result = subprocess.run(
        [ADB_PATH, "-s", device_id, "exec-out", "screencap", "-p"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _iter_jpeg_frames(stream) -> Iterable[bytes]:
    buffer = bytearray()
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 1024 * 1024:
                    buffer.clear()
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start > 0:
                    del buffer[:start]
                break
            frame = bytes(buffer[start : end + 2])
            del buffer[: end + 2]
            yield frame


def _read_exact(stream, size: int) -> Optional[bytes]:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = stream.read(size - len(buffer))
        if not chunk:
            return None
        buffer.extend(chunk)
    return bytes(buffer)


def _recv_exact_socket(
    sock: socket.socket, size: int, timeout: Optional[int] = None
) -> Optional[bytes]:
    deadline = time.time() + max(1, timeout or SCRCPY_READ_TIMEOUT)
    buffer = bytearray()
    while len(buffer) < size and time.time() < deadline:
        try:
            chunk = sock.recv(size - len(buffer))
        except socket.timeout:
            continue
        except OSError:
            return None
        if not chunk:
            return None
        buffer.extend(chunk)
    if len(buffer) < size:
        return None
    return bytes(buffer)


def _recv_exact_socket_buffered(
    sock: socket.socket,
    size: int,
    buffer: bytearray,
    timeout: Optional[int] = None,
) -> Optional[bytes]:
    if size <= 0:
        return b""
    data = bytearray()
    if buffer:
        take = min(size, len(buffer))
        data.extend(buffer[:take])
        del buffer[:take]
        if len(data) == size:
            return bytes(data)
    deadline = time.time() + max(1, timeout or SCRCPY_READ_TIMEOUT)
    while len(data) < size and time.time() < deadline:
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout:
            continue
        except OSError:
            return None
        if not chunk:
            return None
        data.extend(chunk)
    if len(data) < size:
        return None
    return bytes(data)


def _parse_scrcpy_frame_header(header: bytes) -> Tuple[bool, bool, int, int]:
    if len(header) != 12:
        raise ValueError("invalid scrcpy header size")
    pts_flags = int.from_bytes(header[:8], "big")
    config = bool(pts_flags & (1 << 63))
    keyframe = bool(pts_flags & (1 << 62))
    pts = pts_flags & ((1 << 62) - 1)
    size = int.from_bytes(header[8:], "big")
    return config, keyframe, pts, size


def _scrcpy_decode_codec_id(raw: bytes) -> str:
    if len(raw) < 4:
        return ""
    tag = raw[:4]
    try:
        text = tag.decode("ascii", errors="ignore").lower().replace("\x00", "").strip()
    except OSError:
        text = ""
    if text in ("h264", "h265", "av1", "av01", "avc1", "hvc1"):
        if text in ("av01", "av1"):
            return "av1"
        if text == "avc1":
            return "h264"
        if text == "hvc1":
            return "h265"
        return text
    code = int.from_bytes(tag, "big")
    if code == 1:
        return "h264"
    if code == 2:
        return "h265"
    if code == 3:
        return "av1"
    return str(code)


def _scrcpy_read_codec_meta(
    sock: socket.socket, timeout: Optional[int] = None
) -> Optional[Tuple[str, int, int, bytes]]:
    deadline = time.time() + max(1, timeout or SCRCPY_READ_TIMEOUT)
    buffer = bytearray()
    max_buffer = 2048
    while time.time() < deadline:
        try:
            chunk = sock.recv(64)
        except socket.timeout:
            continue
        except OSError:
            return None
        if not chunk:
            return None
        buffer.extend(chunk)
        if len(buffer) > max_buffer:
            del buffer[: len(buffer) - max_buffer]
        if len(buffer) < 12:
            continue
        for i in range(len(buffer) - 11):
            codec_name = _scrcpy_decode_codec_id(buffer[i : i + 4])
            if codec_name not in ("h264", "h265", "av1"):
                continue
            width = int.from_bytes(buffer[i + 4 : i + 8], "big")
            height = int.from_bytes(buffer[i + 8 : i + 12], "big")
            if width <= 0 or height <= 0 or width > 10000 or height > 10000:
                continue
            leftover = bytes(buffer[i + 12 :])
            return codec_name, width, height, leftover
    return None


def _avcc_to_annexb(payload: bytes, length_size: int) -> Optional[bytes]:
    if length_size <= 0:
        return None
    out = bytearray()
    offset = 0
    total = len(payload)
    while offset + length_size <= total:
        nalu_len = int.from_bytes(payload[offset : offset + length_size], "big")
        offset += length_size
        if nalu_len <= 0 or offset + nalu_len > total:
            return None
        out.extend(b"\x00\x00\x00\x01")
        out.extend(payload[offset : offset + nalu_len])
        offset += nalu_len
    if offset != total:
        return None
    return bytes(out)


def _ensure_annexb(payload: bytes) -> bytes:
    if b"\x00\x00\x01" in payload:
        return payload
    converted = _avcc_to_annexb(payload, 4)
    if converted:
        return converted
    converted = _avcc_to_annexb(payload, 2)
    if converted:
        return converted
    return b"\x00\x00\x01" + payload


def _ensure_annexb_with_length(payload: bytes, length_size: Optional[int]) -> bytes:
    if b"\x00\x00\x01" in payload:
        return payload
    if length_size:
        converted = _avcc_to_annexb(payload, length_size)
        if converted:
            return converted
    return _ensure_annexb(payload)


def _parse_avc_config_record(payload: bytes) -> Optional[Tuple[List[bytes], int]]:
    if len(payload) < 7 or payload[0] != 1:
        return None
    length_size = (payload[4] & 0x03) + 1
    num_sps = payload[5] & 0x1F
    offset = 6
    nalus: List[bytes] = []
    for _ in range(num_sps):
        if offset + 2 > len(payload):
            return None
        sps_len = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if offset + sps_len > len(payload):
            return None
        sps = payload[offset : offset + sps_len]
        offset += sps_len
        nalus.append(b"\x00\x00\x00\x01" + sps)
    if offset >= len(payload):
        return None
    num_pps = payload[offset]
    offset += 1
    for _ in range(num_pps):
        if offset + 2 > len(payload):
            return None
        pps_len = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if offset + pps_len > len(payload):
            return None
        pps = payload[offset : offset + pps_len]
        offset += pps_len
        nalus.append(b"\x00\x00\x00\x01" + pps)
    if not nalus:
        return None
    return nalus, length_size


def _split_annexb_nalus(payload: bytes) -> List[bytes]:
    nalus: List[bytes] = []
    i = 0
    while True:
        start = payload.find(b"\x00\x00\x01", i)
        if start < 0:
            break
        if start > 0 and payload[start - 1] == 0:
            start -= 1
        next_start = payload.find(b"\x00\x00\x01", start + 3)
        if next_start < 0:
            nalus.append(payload[start:])
            break
        nalus.append(payload[start:next_start])
        i = next_start
    return nalus


def _nalu_type_from_annexb(nalu: bytes) -> Optional[int]:
    if nalu.startswith(b"\x00\x00\x00\x01"):
        offset = 4
    elif nalu.startswith(b"\x00\x00\x01"):
        offset = 3
    else:
        offset = 0
    if len(nalu) <= offset:
        return None
    return nalu[offset] & 0x1F


def _h264_profile_id_from_sps(nalu: bytes) -> Optional[str]:
    if nalu.startswith(b"\x00\x00\x00\x01"):
        offset = 4
    elif nalu.startswith(b"\x00\x00\x01"):
        offset = 3
    else:
        offset = 0
    if len(nalu) <= offset + 3:
        return None
    profile_idc = nalu[offset + 1]
    profile_iop = nalu[offset + 2]
    level_idc = nalu[offset + 3]
    return "{:02x}{:02x}{:02x}".format(profile_idc, profile_iop, level_idc)


def _parse_fmtp_params(value: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            params[key.strip()] = val.strip()
        else:
            params[part] = ""
    return params


def _h264_profiles_from_offer(offer_sdp: str) -> List[Tuple[str, str]]:
    rtpmap: Dict[str, str] = {}
    fmtp: Dict[str, Dict[str, str]] = {}
    payload_order: List[str] = []
    for line in offer_sdp.splitlines():
        line = line.strip()
        if line.startswith("m=video"):
            parts = line.split()
            payload_order = parts[3:]
            continue
        if line.startswith("a=rtpmap:"):
            value = line[len("a=rtpmap:") :]
            if " " not in value:
                continue
            pt, rest = value.split(" ", 1)
            codec = rest.split("/", 1)[0].strip().lower()
            rtpmap[pt] = codec
            continue
        if line.startswith("a=fmtp:"):
            value = line[len("a=fmtp:") :]
            if " " not in value:
                continue
            pt, params = value.split(" ", 1)
            fmtp[pt] = _parse_fmtp_params(params)
    profiles: List[Tuple[str, str]] = []
    for pt in payload_order:
        if rtpmap.get(pt) != "h264":
            continue
        params = fmtp.get(pt, {})
        profile = params.get("profile-level-id", "42e01f").lower()
        packetization = params.get("packetization-mode", "0")
        profiles.append((profile, packetization))
    return profiles


def _choose_h264_profile_for_offer(
    offer_sdp: str, desired_profile: Optional[aiortc_sdp.H264Profile]
) -> Optional[str]:
    candidates = _h264_profiles_from_offer(offer_sdp)
    if not candidates:
        return None
    if desired_profile:
        for profile, packetization in candidates:
            if packetization != "1":
                continue
            try:
                profile_class, _ = aiortc_sdp.parse_h264_profile_level_id(profile)
            except ValueError:
                continue
            if profile_class == desired_profile:
                return profile
    for profile, packetization in candidates:
        if packetization == "1":
            return profile
    return candidates[0][0]


def _terminate_process(process: Optional[subprocess.Popen]) -> None:
    if not process:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def _build_screenrecord_cmd(device_id: str) -> List[str]:
    if STREAM_SEGMENT_SECONDS <= 0:
        segment_seconds = 0
    else:
        segment_seconds = max(1, min(STREAM_SEGMENT_SECONDS, 180))
    size_args = _screenrecord_size_args(device_id)
    return [
        ADB_PATH,
        "-s",
        device_id,
        "exec-out",
        "screenrecord",
        "--output-format=h264",
        "--bit-rate",
        str(STREAM_BITRATE),
        "--time-limit",
        str(segment_seconds),
        *size_args,
        "-",
    ]


def _build_screenrecord_probe_cmd(device_id: str) -> List[str]:
    size_args = _screenrecord_size_args(device_id)
    return [
        ADB_PATH,
        "-s",
        device_id,
        "exec-out",
        "screenrecord",
        "--output-format=h264",
        "--bit-rate",
        str(STREAM_BITRATE),
        "--time-limit",
        "2",
        *size_args,
        "-",
    ]


def _screenrecord_size_args(device_id: str) -> List[str]:
    if STREAM_SCALE <= 0:
        return []
    try:
        width, height = _adb_screen_size(device_id)
    except HTTPException:
        return []
    target_width, target_height = _scaled_dimensions(width, height)
    if target_width == width and target_height == height:
        return []
    return ["--size", "{}x{}".format(target_width, target_height)]


def _probe_h264_profile_id(device_id: str) -> Optional[str]:
    cached = _H264_PROFILE_CACHE.get(device_id)
    if cached:
        return cached
    screen = None
    deadline = time.time() + max(1, min(3, STREAM_DETECTION_TIMEOUT))
    try:
        parser = av.CodecContext.create("h264", "r")
        screen = subprocess.Popen(
            _build_screenrecord_probe_cmd(device_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if not screen.stdout:
            return None
        while time.time() < deadline:
            chunk = screen.stdout.read(4096)
            if not chunk:
                break
            packets = parser.parse(chunk)
            for packet in packets:
                payload = _ensure_annexb(bytes(packet))
                for nalu in _split_annexb_nalus(payload):
                    if _nalu_type_from_annexb(nalu) != 7:
                        continue
                    profile = _h264_profile_id_from_sps(nalu)
                    if profile:
                        _H264_PROFILE_CACHE[device_id] = profile
                        print(
                            "[webrtc] h264 profile",
                            device_id,
                            profile,
                            flush=True,
                        )
                        return profile
    finally:
        _terminate_process(screen)
    return None


def _probe_scrcpy_h264_profile_id(
    device_id: str, force: bool = False
) -> Optional[str]:
    if force:
        _SCRCPY_PROFILE_CACHE.pop(device_id, None)
    cached = _SCRCPY_PROFILE_CACHE.get(device_id)
    if cached and not force:
        return cached
    process = None
    port = None
    sock = None
    deadline = time.time() + max(2, SCRCPY_CONNECT_TIMEOUT)
    try:
        process, port, scid = _scrcpy_start_server(device_id)
        if SCRCPY_START_DELAY_MS > 0:
            time.sleep(SCRCPY_START_DELAY_MS / 1000.0)
        sock = _scrcpy_connect_socket(port, SCRCPY_CONNECT_TIMEOUT)
        meta = _scrcpy_read_codec_meta(sock, SCRCPY_READ_TIMEOUT)
        if not meta:
            return None
        codec_name, _width, _height, leftover = meta
        if codec_name != "h264":
            return None
        buffer = bytearray(leftover)
        while time.time() < deadline:
            header = _recv_exact_socket_buffered(sock, 12, buffer)
            if not header:
                break
            try:
                _config, _keyframe, _pts, size = _parse_scrcpy_frame_header(header)
            except ValueError:
                break
            if size <= 0:
                continue
            payload = _recv_exact_socket_buffered(sock, size, buffer)
            if not payload:
                break
            parsed = _parse_avc_config_record(payload)
            if parsed:
                nalus, _length_size = parsed
            else:
                payload = _ensure_annexb(payload)
                nalus = _split_annexb_nalus(payload)
            for nalu in nalus:
                if _nalu_type_from_annexb(nalu) != 7:
                    continue
                profile = _h264_profile_id_from_sps(nalu)
                if profile:
                    _SCRCPY_PROFILE_CACHE[device_id] = profile
                    print(
                        "[webrtc] scrcpy profile",
                        device_id,
                        profile,
                        flush=True,
                    )
                    return profile
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        _terminate_process(process)
        _scrcpy_forward_remove(device_id, port)
    return None


def _allocate_dynamic_payload_pair() -> Tuple[int, int]:
    used = {codec.payloadType for codec in aiortc_codecs.CODECS["video"]}
    for pt in range(96, 127):
        if pt in used or pt + 1 in used:
            continue
        return pt, pt + 1
    highest = max(used or {95})
    return highest + 1, highest + 2


def _ensure_h264_codec(profile_level_id: str) -> None:
    profile_level_id = profile_level_id.lower()
    for codec in aiortc_codecs.CODECS["video"]:
        if codec.mimeType.lower() != "video/h264":
            continue
        if codec.parameters.get("profile-level-id", "").lower() != profile_level_id:
            continue
        if codec.parameters.get("packetization-mode") == "1":
            return
    payload_type, rtx_payload_type = _allocate_dynamic_payload_pair()
    feedback = [
        RTCRtcpFeedback(type="nack"),
        RTCRtcpFeedback(type="nack", parameter="pli"),
        RTCRtcpFeedback(type="goog-remb"),
    ]
    aiortc_codecs.CODECS["video"].append(
        RTCRtpCodecParameters(
            mimeType="video/H264",
            clockRate=90000,
            payloadType=payload_type,
            rtcpFeedback=feedback,
            parameters={
                "level-asymmetry-allowed": "1",
                "packetization-mode": "1",
                "profile-level-id": profile_level_id,
            },
        )
    )
    aiortc_codecs.CODECS["video"].append(
        RTCRtpCodecParameters(
            mimeType="video/rtx",
            clockRate=90000,
            payloadType=rtx_payload_type,
            parameters={"apt": payload_type},
        )
    )


def _apply_h264_preference(
    transceiver, device_id: str, profile_level_id: str
) -> None:
    profile_level_id = profile_level_id.lower()
    capabilities = RTCRtpSender.getCapabilities("video")
    preferred = []
    rtx = []
    for codec in capabilities.codecs:
        mime = codec.mimeType.lower()
        if mime == "video/h264":
            params = codec.parameters or {}
            if params.get("profile-level-id", "").lower() == profile_level_id:
                if params.get("packetization-mode", "1") == "1":
                    preferred.append(codec)
        elif mime == "video/rtx":
            rtx.append(codec)
    if not preferred:
        return
    ordered = preferred + rtx + [c for c in capabilities.codecs if c not in preferred and c not in rtx]
    transceiver.setCodecPreferences(ordered)
    print("[webrtc] prefer h264", device_id, profile_level_id, flush=True)


def _build_ffmpeg_cmd() -> List[str]:
    filters = []
    if STREAM_SCALE > 0:
        filters.append("scale=-2:{}".format(STREAM_SCALE))
    filters.append("fps={}".format(max(1, STREAM_FPS)))
    filter_expr = ",".join(filters)
    return [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-analyzeduration",
        str(max(0, STREAM_ANALYZE_US)),
        "-probesize",
        str(max(32, STREAM_PROBESIZE)),
        "-f",
        "h264",
        "-i",
        "pipe:0",
        "-vf",
        filter_expr,
        "-f",
        "mjpeg",
        "-q:v",
        str(max(2, STREAM_QUALITY)),
        "pipe:1",
    ]


def _build_ffmpeg_raw_cmd(width: int, height: int) -> List[str]:
    filters = ["scale={}:{}".format(width, height)]
    filters.append("fps={}".format(max(1, STREAM_FPS)))
    filter_expr = ",".join(filters)
    return [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-analyzeduration",
        str(max(0, STREAM_ANALYZE_US)),
        "-probesize",
        str(max(32, STREAM_PROBESIZE)),
        "-f",
        "h264",
        "-i",
        "pipe:0",
        "-vf",
        filter_expr,
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def _build_ffmpeg_cmd_mkv() -> List[str]:
    filters = ["fps={}".format(max(1, STREAM_FPS))]
    filter_expr = ",".join(filters)
    return [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-analyzeduration",
        str(max(0, STREAM_ANALYZE_US)),
        "-probesize",
        str(max(32, STREAM_PROBESIZE)),
        "-f",
        "matroska",
        "-i",
        "pipe:0",
        "-vf",
        filter_expr,
        "-f",
        "mjpeg",
        "-q:v",
        str(max(2, STREAM_QUALITY)),
        "pipe:1",
    ]


class AdbVideoTrack(VideoStreamTrack):
    def __init__(self, device_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._device_id = device_id
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._screen: Optional[subprocess.Popen] = None
        self._ffmpeg: Optional[subprocess.Popen] = None
        width, height = _adb_screen_size(device_id)
        self._width, self._height = _scaled_dimensions(width, height)
        self._frame_size = self._width * self._height * 3
        self._fps = max(1, STREAM_FPS)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _queue_frame(self, frame) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(frame)

    def _set_processes(
        self,
        screen: Optional[subprocess.Popen],
        ffmpeg: Optional[subprocess.Popen],
    ) -> None:
        with self._lock:
            self._screen = screen
            self._ffmpeg = ffmpeg

    def _reader(self) -> None:
        while not self._stop_event.is_set():
            screen = None
            ffmpeg = None
            try:
                screen = subprocess.Popen(
                    _build_screenrecord_cmd(self._device_id),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                ffmpeg = subprocess.Popen(
                    _build_ffmpeg_raw_cmd(self._width, self._height),
                    stdin=screen.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._set_processes(screen, ffmpeg)
                if screen.stdout:
                    screen.stdout.close()
                if not ffmpeg.stdout:
                    break
                while not self._stop_event.is_set():
                    chunk = _read_exact(ffmpeg.stdout, self._frame_size)
                    if not chunk:
                        break
                    frame = np.frombuffer(chunk, dtype=np.uint8)
                    frame = frame.reshape((self._height, self._width, 3))
                    try:
                        self._loop.call_soon_threadsafe(self._queue_frame, frame)
                    except RuntimeError:
                        self._stop_event.set()
                        break
            finally:
                self._set_processes(None, None)
                _terminate_process(ffmpeg)
                _terminate_process(screen)
                if not self._stop_event.is_set():
                    time.sleep(0.05)

    async def recv(self) -> VideoFrame:
        frame = await self._queue.get()
        pts, time_base = await self.next_timestamp()
        video = VideoFrame.from_ndarray(frame, format="bgr24")
        video.pts = pts
        video.time_base = time_base
        return video

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        with self._lock:
            _terminate_process(self._ffmpeg)
            _terminate_process(self._screen)
        super().stop()


class ScreencapVideoTrack(VideoStreamTrack):
    def __init__(self, device_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._device_id = device_id
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _queue_frame(self, frame) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(frame)

    def _reader(self) -> None:
        interval = 1.0 / max(1, STREAM_FPS)
        while not self._stop_event.is_set():
            start = time.time()
            payload = _screencap_bytes(self._device_id)
            if payload:
                data = np.frombuffer(payload, dtype=np.uint8)
                frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if frame is not None:
                    if STREAM_SCALE > 0 and frame.shape[0] > STREAM_SCALE:
                        scale = STREAM_SCALE / float(frame.shape[0])
                        target_width = max(2, int(frame.shape[1] * scale))
                        target_height = max(2, int(frame.shape[0] * scale))
                        frame = cv2.resize(frame, (target_width, target_height))
                    try:
                        self._loop.call_soon_threadsafe(self._queue_frame, frame)
                    except RuntimeError:
                        self._stop_event.set()
                        break
            elapsed = time.time() - start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    async def recv(self) -> VideoFrame:
        frame = await self._queue.get()
        pts, time_base = await self.next_timestamp()
        video = VideoFrame.from_ndarray(frame, format="bgr24")
        video.pts = pts
        video.time_base = time_base
        return video

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        super().stop()


class H264ScreenrecordTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, device_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._device_id = device_id
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._lock = threading.Lock()
        self._screen: Optional[subprocess.Popen] = None
        self._frame_index = 0
        self._time_base = fractions.Fraction(1, max(1, STREAM_FPS))
        self._need_keyframe = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _queue_packet(self, packet: Packet) -> None:
        if self._need_keyframe and self._queue.full():
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(packet)

    def _set_process(self, screen: Optional[subprocess.Popen]) -> None:
        with self._lock:
            self._screen = screen

    def request_keyframe(self) -> None:
        if self._stop_event.is_set():
            return
        self._need_keyframe = True
        self._restart_event.set()
        with self._lock:
            _terminate_process(self._screen)

    def _reader(self) -> None:
        while not self._stop_event.is_set():
            screen = None
            try:
                parser = av.CodecContext.create("h264", "r")
                screen = subprocess.Popen(
                    _build_screenrecord_cmd(self._device_id),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._set_process(screen)
                if not screen.stdout:
                    break
                logged = False
                bytes_read = 0
                packets_seen = 0
                sps = None
                pps = None
                while not self._stop_event.is_set():
                    if self._restart_event.is_set():
                        self._restart_event.clear()
                        break
                    chunk = screen.stdout.read(4096)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    packets = parser.parse(chunk)
                    if not logged:
                        print(
                            "[webrtc] h264 read",
                            self._device_id,
                            "bytes",
                            len(chunk),
                            "packets",
                            len(packets),
                            flush=True,
                        )
                        logged = True
                    for packet in packets:
                        payload = _ensure_annexb(bytes(packet))
                        nalus = _split_annexb_nalus(payload)
                        types = []
                        for nalu in nalus:
                            nal_type = _nalu_type_from_annexb(nalu)
                            if nal_type is None:
                                continue
                            types.append(nal_type)
                            if nal_type == 7:
                                sps = nalu
                            elif nal_type == 8:
                                pps = nalu
                        has_vcl = any(nal_type in (1, 5) for nal_type in types)
                        is_idr = 5 in types
                        if not has_vcl:
                            continue
                        if self._need_keyframe and not is_idr:
                            continue
                        output_nalus = []
                        if is_idr and sps and pps and 7 not in types and 8 not in types:
                            output_nalus.extend([sps, pps])
                        output_nalus.extend(nalus)
                        packet = Packet(b"".join(output_nalus))
                        packet.pts = self._frame_index
                        packet.dts = self._frame_index
                        packet.time_base = self._time_base
                        self._frame_index += 1
                        packets_seen += 1
                        if is_idr and self._need_keyframe:
                            self._need_keyframe = False
                            print(
                                "[webrtc] h264 keyframe",
                                self._device_id,
                                "frame",
                                self._frame_index,
                                flush=True,
                            )
                        if packets_seen == 1:
                            total_size = sum(len(nalu) for nalu in output_nalus) if output_nalus else len(payload)
                            print(
                                "[webrtc] h264 packet",
                                self._device_id,
                                "size",
                                total_size,
                                "nal_types",
                                types,
                                "total_bytes",
                                bytes_read,
                                flush=True,
                            )
                        try:
                            self._loop.call_soon_threadsafe(self._queue_packet, packet)
                        except RuntimeError:
                            self._stop_event.set()
                            break
                        if packets_seen == 0 and bytes_read >= 200_000:
                            print(
                                "[webrtc] h264 no packets after",
                                bytes_read,
                                "bytes",
                                self._device_id,
                                flush=True,
                            )
                            bytes_read = 0
            finally:
                self._set_process(None)
                _terminate_process(screen)
                if not self._stop_event.is_set():
                    time.sleep(0.05)

    async def recv(self) -> Packet:
        packet = await self._queue.get()
        return packet

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._restart_event.set()
        with self._lock:
            _terminate_process(self._screen)
        super().stop()


def _scrcpy_server_available() -> bool:
    if Path(SCRCPY_SERVER_PATH).exists():
        return True
    return shutil.which(SCRCPY_SERVER_PATH) is not None


def _scrcpy_server_scid() -> str:
    value = random.randint(1, 0x7FFFFFFF)
    return "{:x}".format(value)


def _scrcpy_allocate_port(force_dynamic: bool = False) -> int:
    if SCRCPY_SERVER_PORT > 0 and not force_dynamic:
        return SCRCPY_SERVER_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _scrcpy_forward(device_id: str, port: int, scid: str) -> None:
    result = subprocess.run(
        [
            ADB_PATH,
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
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError("adb forward failed: {}".format(message))


def _scrcpy_forward_remove(device_id: str, port: Optional[int]) -> None:
    if not port:
        return
    try:
        subprocess.run(
            [
                ADB_PATH,
                "-s",
                device_id,
                "forward",
                "--remove",
                "tcp:{}".format(port),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _scrcpy_push_server(device_id: str) -> None:
    result = subprocess.run(
        [
            ADB_PATH,
            "-s",
            device_id,
            "push",
            SCRCPY_SERVER_PATH,
            "/data/local/tmp/scrcpy-server.jar",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError("adb push scrcpy-server failed: {}".format(message))


def _build_scrcpy_server_cmd(device_id: str, scid: str) -> List[str]:
    cmd = [
        ADB_PATH,
        "-s",
        device_id,
        "shell",
        "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
        "app_process",
        "/",
        "com.genymobile.scrcpy.Server",
        SCRCPY_SERVER_VERSION,
        "scid={}".format(scid),
        *(["log_level={}".format(SCRCPY_LOG_LEVEL)] if SCRCPY_LOG_LEVEL else []),
        "tunnel_forward=true",
        "audio=false",
        "control=false",
        "cleanup=false",
        "send_device_meta=false",
        "send_dummy_byte=false",
        "send_codec_meta=true",
        "send_frame_meta=true",
        "video_codec=h264",
        "max_fps={}".format(max(1, STREAM_FPS)),
        "video_bit_rate={}".format(max(1, STREAM_BITRATE)),
    ]
    if STREAM_SCALE > 0:
        cmd.append("max_size={}".format(STREAM_SCALE))
    if SCRCPY_VIDEO_OPTIONS:
        cmd.append("video_codec_options={}".format(SCRCPY_VIDEO_OPTIONS))
    return cmd


def _scrcpy_wait_for_socket(
    device_id: str, scid: str, timeout: int
) -> bool:
    deadline = time.time() + max(1, timeout)
    target = "scrcpy_{}".format(scid)
    while time.time() < deadline:
        result = subprocess.run(
            [ADB_PATH, "-s", device_id, "shell", "ls", "/dev/socket"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and target in (result.stdout or ""):
            return True
        time.sleep(0.2)
    return False


def _scrcpy_log_reader(device_id: str, process: subprocess.Popen) -> None:
    if not process.stdout:
        return
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        print("[scrcpy]", device_id, line, flush=True)


def _scrcpy_start_server(device_id: str) -> Tuple[subprocess.Popen, int, str]:
    _scrcpy_push_server(device_id)
    scid = _scrcpy_server_scid()
    port = _scrcpy_allocate_port()
    _scrcpy_forward_remove(device_id, port)
    try:
        _scrcpy_forward(device_id, port, scid)
    except RuntimeError:
        if SCRCPY_SERVER_PORT > 0:
            port = _scrcpy_allocate_port(force_dynamic=True)
            _scrcpy_forward_remove(device_id, port)
            _scrcpy_forward(device_id, port, scid)
        else:
            raise
    cmd = _build_scrcpy_server_cmd(device_id, scid)
    if SCRCPY_LOG_LEVEL:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(
            target=_scrcpy_log_reader,
            args=(device_id, process),
            daemon=True,
        ).start()
        print("[webrtc] scrcpy cmd", device_id, " ".join(cmd), flush=True)
    else:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return process, port, scid


def _scrcpy_connect_socket(port: int, timeout: int) -> socket.socket:
    deadline = time.time() + max(1, timeout)
    last_error = None
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(max(1, SCRCPY_READ_TIMEOUT))
            return sock
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError("scrcpy connect failed: {}".format(last_error))


class ScrcpyH264Track(MediaStreamTrack):
    kind = "video"

    def __init__(self, device_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._device_id = device_id
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._lock = threading.Lock()
        self._socket: Optional[socket.socket] = None
        self._process: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._length_size: Optional[int] = None
        self._time_base = fractions.Fraction(1, 1_000_000)
        self._need_keyframe = True
        self._frame_index = 0
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _queue_packet(self, packet: Packet) -> None:
        if self._need_keyframe and self._queue.full():
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(packet)

    def _set_session(
        self,
        process: Optional[subprocess.Popen],
        port: Optional[int],
        sock: Optional[socket.socket],
    ) -> None:
        with self._lock:
            self._process = process
            self._port = port
            self._socket = sock

    def _stop_session(self) -> None:
        with self._lock:
            sock = self._socket
            process = self._process
            port = self._port
            self._socket = None
            self._process = None
            self._port = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        _terminate_process(process)
        _scrcpy_forward_remove(self._device_id, port)

    def request_keyframe(self) -> None:
        if self._stop_event.is_set():
            return
        self._need_keyframe = True
        self._restart_event.set()
        self._stop_session()

    def _reader(self) -> None:
        while not self._stop_event.is_set():
            process = None
            port = None
            sock = None
            try:
                process, port, scid = _scrcpy_start_server(self._device_id)
                print(
                    "[webrtc] scrcpy start",
                    self._device_id,
                    "port",
                    port,
                    flush=True,
                )
                if SCRCPY_START_DELAY_MS > 0:
                    time.sleep(SCRCPY_START_DELAY_MS / 1000.0)
                self._set_session(process, port, None)
                meta = None
                buffer = bytearray()
                for _ in range(max(1, SCRCPY_META_RETRIES)):
                    sock = _scrcpy_connect_socket(port, SCRCPY_CONNECT_TIMEOUT)
                    self._set_session(process, port, sock)
                    meta = _scrcpy_read_codec_meta(sock, SCRCPY_READ_TIMEOUT)
                    if meta:
                        break
                    try:
                        sock.close()
                    except OSError:
                        pass
                    sock = None
                    time.sleep(0.2)
                if not meta:
                    exit_code = process.poll() if process else None
                    print(
                        "[webrtc] scrcpy meta missing",
                        self._device_id,
                        "exit",
                        exit_code,
                        flush=True,
                    )
                    continue
                codec_name, width, height, leftover = meta
                buffer = bytearray(leftover)
                print(
                    "[webrtc] scrcpy meta",
                    self._device_id,
                    codec_name,
                    "{}x{}".format(width, height),
                    flush=True,
                )
                if codec_name != "h264":
                    print(
                        "[webrtc] scrcpy unsupported codec",
                        self._device_id,
                        codec_name,
                        flush=True,
                    )
                    self._stop_event.set()
                    break
                sps = None
                pps = None
                logged_packet = False
                logged_config = False
                logged_wait_keyframe = False
                logged_empty_nalus = False
                logged_length_unknown = False
                while not self._stop_event.is_set():
                    if self._restart_event.is_set():
                        self._restart_event.clear()
                        break
                    header = _recv_exact_socket_buffered(sock, 12, buffer)
                    if not header:
                        break
                    try:
                        config, keyframe, pts, size = _parse_scrcpy_frame_header(
                            header
                        )
                    except ValueError:
                        break
                    if size <= 0:
                        continue
                    raw_payload = _recv_exact_socket_buffered(
                        sock, size, buffer
                    )
                    if not raw_payload:
                        break
                    if config:
                        parsed = _parse_avc_config_record(raw_payload)
                        if parsed:
                            nalus, length_size = parsed
                            self._length_size = length_size
                        else:
                            payload = _ensure_annexb_with_length(
                                raw_payload, self._length_size
                            )
                            nalus = _split_annexb_nalus(payload)
                        if not logged_config:
                            print(
                                "[webrtc] scrcpy config",
                                self._device_id,
                                "size",
                                size,
                                "length",
                                self._length_size,
                                flush=True,
                            )
                            logged_config = True
                    else:
                        if (
                            self._length_size is None
                            and b"\x00\x00\x01" not in raw_payload
                            and not logged_length_unknown
                        ):
                            print(
                                "[webrtc] scrcpy length unknown",
                                self._device_id,
                                "size",
                                size,
                                flush=True,
                            )
                            logged_length_unknown = True
                        payload = _ensure_annexb_with_length(
                            raw_payload, self._length_size
                        )
                        nalus = _split_annexb_nalus(payload)
                    if not nalus:
                        if not logged_empty_nalus:
                            print(
                                "[webrtc] scrcpy empty nalus",
                                self._device_id,
                                flush=True,
                            )
                            logged_empty_nalus = True
                        continue
                    if config:
                        for nalu in nalus:
                            nal_type = _nalu_type_from_annexb(nalu)
                            if nal_type == 7:
                                sps = nalu
                                profile = _h264_profile_id_from_sps(nalu)
                                if profile and self._device_id not in _SCRCPY_PROFILE_CACHE:
                                    _SCRCPY_PROFILE_CACHE[self._device_id] = profile
                                    print(
                                        "[webrtc] scrcpy profile",
                                        self._device_id,
                                        profile,
                                        flush=True,
                                    )
                            elif nal_type == 8:
                                pps = nalu
                        continue
                    types = []
                    for nalu in nalus:
                        nal_type = _nalu_type_from_annexb(nalu)
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
                    if self._need_keyframe and not is_idr:
                        if not logged_wait_keyframe:
                            print(
                                "[webrtc] scrcpy wait keyframe",
                                self._device_id,
                                "types",
                                types,
                                "keyframe",
                                keyframe,
                                flush=True,
                            )
                            logged_wait_keyframe = True
                        continue
                    output_nalus = []
                    if is_idr and sps and pps and (7 not in types or 8 not in types):
                        output_nalus.extend([sps, pps])
                    output_nalus.extend(nalus)
                    packet = Packet(b"".join(output_nalus))
                    packet.pts = pts
                    packet.dts = pts
                    packet.time_base = self._time_base
                    self._frame_index += 1
                    if is_idr and self._need_keyframe:
                        self._need_keyframe = False
                        print(
                            "[webrtc] scrcpy keyframe",
                            self._device_id,
                            "pts",
                            pts,
                            flush=True,
                        )
                    if not logged_packet:
                        print(
                            "[webrtc] scrcpy packet",
                            self._device_id,
                            "size",
                            sum(len(nalu) for nalu in output_nalus),
                            "nal_types",
                            types,
                            flush=True,
                        )
                        logged_packet = True
                    try:
                        self._loop.call_soon_threadsafe(self._queue_packet, packet)
                    except RuntimeError:
                        self._stop_event.set()
                        break
            except Exception as exc:
                print(
                    "[webrtc] scrcpy error",
                    self._device_id,
                    str(exc),
                    flush=True,
                )
            finally:
                self._stop_session()
                if not self._stop_event.is_set():
                    time.sleep(0.1)

    async def recv(self) -> Packet:
        packet = await self._queue.get()
        return packet

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._restart_event.set()
        self._stop_session()
        super().stop()


def _scrcpy_available() -> bool:
    if Path(SCRCPY_PATH).exists():
        return True
    return shutil.which(SCRCPY_PATH) is not None


def _build_scrcpy_cmd(device_id: str, record_path: Path) -> List[str]:
    cmd = [
        SCRCPY_PATH,
        "--no-playback",
        "--no-audio",
        "--no-control",
        "-s",
        device_id,
        "--record",
        str(record_path),
        "--record-format",
        STREAM_SCRCPY_FORMAT,
        "--max-fps",
        str(max(1, STREAM_FPS)),
        "--video-bit-rate",
        str(max(1, STREAM_BITRATE)),
        "--verbosity=error",
    ]
    if STREAM_SCALE > 0:
        cmd.extend(["--max-size", str(STREAM_SCALE)])
    return cmd


def _tail_file_to_pipe(path: Path, pipe, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        if not path.exists():
            time.sleep(0.1)
            continue
        try:
            with path.open("rb") as handle:
                while not stop_event.is_set():
                    chunk = handle.read(8192)
                    if chunk:
                        try:
                            pipe.write(chunk)
                            pipe.flush()
                        except BrokenPipeError:
                            stop_event.set()
                            break
                    else:
                        time.sleep(0.05)
        except OSError:
            time.sleep(0.1)


def _mjpeg_stream_screenrecord(device_id: str) -> Iterable[bytes]:
    _require_binary(ADB_PATH, "adb")
    _require_binary(FFMPEG_PATH, "ffmpeg")
    boundary = b"--frame\r\n"
    header_template = b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
    while True:
        screen = None
        ffmpeg = None
        try:
            screen = subprocess.Popen(
                _build_screenrecord_cmd(device_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            ffmpeg = subprocess.Popen(
                _build_ffmpeg_cmd(),
                stdin=screen.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if screen.stdout:
                screen.stdout.close()
            if not ffmpeg.stdout:
                break
            for frame in _iter_jpeg_frames(ffmpeg.stdout):
                header = header_template % len(frame)
                yield boundary + header + frame + b"\r\n"
        except GeneratorExit:
            break
        finally:
            _terminate_process(ffmpeg)
            _terminate_process(screen)


def _mjpeg_stream_scrcpy(device_id: str) -> Iterable[bytes]:
    _require_binary(SCRCPY_PATH, "scrcpy")
    _require_binary(FFMPEG_PATH, "ffmpeg")
    boundary = b"--frame\r\n"
    header_template = b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
    stream_dir = OUTPUTS_DIR / "streams" / device_id
    stream_dir.mkdir(parents=True, exist_ok=True)
    record_path = stream_dir / "scrcpy_{}.{}".format(int(time.time() * 1000), STREAM_SCRCPY_FORMAT)
    stop_event = threading.Event()
    tail_thread = None
    scrcpy = None
    ffmpeg = None
    env = dict(os.environ)
    env["ADB"] = ADB_PATH
    scrcpy_dir = Path(SCRCPY_PATH).parent
    if Path(SCRCPY_SERVER_PATH).exists():
        env["SCRCPY_SERVER_PATH"] = str(SCRCPY_SERVER_PATH)
    try:
        scrcpy = subprocess.Popen(
            _build_scrcpy_cmd(device_id, record_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=str(scrcpy_dir),
        )
        ffmpeg = subprocess.Popen(
            _build_ffmpeg_cmd_mkv(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if ffmpeg.stdin:
            tail_thread = threading.Thread(
                target=_tail_file_to_pipe,
                args=(record_path, ffmpeg.stdin, stop_event),
                daemon=True,
            )
            tail_thread.start()
        if not ffmpeg.stdout:
            return
        for frame in _iter_jpeg_frames(ffmpeg.stdout):
            header = header_template % len(frame)
            yield boundary + header + frame + b"\r\n"
    except GeneratorExit:
        pass
    finally:
        stop_event.set()
        if ffmpeg and ffmpeg.stdin:
            try:
                ffmpeg.stdin.close()
            except OSError:
                pass
        if tail_thread:
            tail_thread.join(timeout=1)
        _terminate_process(ffmpeg)
        _terminate_process(scrcpy)
        try:
            record_path.unlink()
        except OSError:
            pass


def _mjpeg_stream_screencap(device_id: str) -> Iterable[bytes]:
    boundary = b"--frame\r\n"
    header_template = b"Content-Type: image/png\r\nContent-Length: %d\r\n\r\n"
    fallback_fps = max(1, min(STREAM_FPS, 10))
    interval = 1.0 / fallback_fps
    while True:
        start = time.time()
        frame = _screencap_bytes(device_id)
        if not frame:
            break
        header = header_template % len(frame)
        yield boundary + header + frame + b"\r\n"
        elapsed = time.time() - start
        if elapsed < interval:
            time.sleep(interval - elapsed)


def _mjpeg_stream(device_id: str) -> Iterable[bytes]:
    if not _scrcpy_available():
        raise HTTPException(status_code=500, detail="scrcpy not found")
    if not _scrcpy_server_available():
        raise HTTPException(status_code=500, detail="scrcpy-server not found")
    return _mjpeg_stream_scrcpy(device_id)


def _webrtc_configuration() -> Optional[RTCConfiguration]:
    if not WEBRTC_ICE_URLS:
        return None
    servers = [RTCIceServer(urls=[url]) for url in WEBRTC_ICE_URLS]
    return RTCConfiguration(iceServers=servers)


def _select_webrtc_track(
    device_id: str,
    loop: asyncio.AbstractEventLoop,
    source_override: Optional[str] = None,
) -> MediaStreamTrack:
    source = (source_override or WEBRTC_SOURCE).strip().lower()
    if source in ("scrcpy", "auto"):
        return ScrcpyH264Track(device_id, loop)
    raise HTTPException(status_code=400, detail="only scrcpy source supported")


async def _wait_for_ice_gathering(pc: RTCPeerConnection) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def on_state_change() -> None:
        if pc.iceGatheringState == "complete":
            done.set()

    await done.wait()


def _list_steps(run_dir: Path) -> List[Dict[str, object]]:
    steps = []
    for step_dir in sorted(run_dir.glob("step_*")):
        if not step_dir.is_dir():
            continue
        step_id = step_dir.name
        decision = _read_json(step_dir / "decision.json") or {}
        steps.append(
            {
                "id": step_id,
                "decision": decision,
                "has_screen": (step_dir / "screen.png").exists(),
                "updated_time": step_dir.stat().st_mtime,
            }
        )
    return steps


def _step_payload(run_id: str, step_id: str, step_dir: Path) -> Dict[str, object]:
    return {
        "run_id": run_id,
        "step_id": step_id,
        "decision": _read_json(step_dir / "decision.json"),
        "prompt": _read_text(step_dir / "prompt.txt"),
        "response": _read_text(step_dir / "response.txt"),
        "context": _read_json(step_dir / "context.json"),
        "ocr_payload": _read_json(step_dir / "ocr_payload.json"),
        "verification": _read_json(step_dir / "verification.json"),
        "screen_url": "/outputs/{}/{}".format(run_id, "screen.png"),
        "step_screen_url": "/outputs/{}/{}".format(run_id, "{}/screen.png".format(step_id)),
        "step_after_url": "/outputs/{}/{}".format(run_id, "{}/screen_after.png".format(step_id)),
    }


app = FastAPI()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
run_manager = RunManager(OUTPUTS_DIR)
pcs: Set[RTCPeerConnection] = set()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    coros = [pc.close() for pc in pcs]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)
    pcs.clear()


@app.get("/api/runs")
def list_runs():
    return JSONResponse(run_manager.list_runs())


@app.get("/api/devices")
def list_devices():
    return JSONResponse(_list_adb_devices())


@app.get("/api/stream/{device_id}.mjpg")
def stream_device(device_id: str):
    device_id = _validate_device_id(device_id)
    devices = _list_adb_devices()
    match = next((item for item in devices if item["id"] == device_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="device not found")
    if match.get("status") != "device":
        raise HTTPException(status_code=409, detail="device not ready")
    generator = _mjpeg_stream(device_id)
    return StreamingResponse(
        generator,
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/webrtc/config")
def webrtc_config():
    return JSONResponse({"ice_servers": WEBRTC_ICE_URLS})


@app.post("/api/webrtc/offer")
async def webrtc_offer(payload: WebRTCOffer):
    device_id = _validate_device_id(payload.device_id)
    if payload.type != "offer":
        raise HTTPException(status_code=400, detail="invalid sdp type")
    devices = _list_adb_devices()
    match = next((item for item in devices if item["id"] == device_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="device not found")
    if match.get("status") != "device":
        raise HTTPException(status_code=409, detail="device not ready")
    configuration = _webrtc_configuration()
    if configuration:
        pc = RTCPeerConnection(configuration=configuration)
    else:
        pc = RTCPeerConnection()
    pcs.add(pc)
    loop = asyncio.get_running_loop()
    _require_binary(ADB_PATH, "adb")
    _require_binary(SCRCPY_SERVER_PATH, "scrcpy-server")
    preferred_profile = None
    offer_profiles = _h264_profiles_from_offer(payload.sdp)
    offer_h264_profiles = [
        profile.lower()
        for profile, packetization in offer_profiles
        if profile and packetization == "1"
    ]
    if not offer_h264_profiles:
        raise HTTPException(status_code=409, detail="client does not offer h264")
    if FORCED_H264_PROFILE:
        if FORCED_H264_PROFILE in offer_h264_profiles:
            preferred_profile = FORCED_H264_PROFILE
            print(
                "[webrtc] forced profile",
                device_id,
                preferred_profile,
                flush=True,
            )
        else:
            print(
                "[webrtc] forced profile not in offer",
                device_id,
                FORCED_H264_PROFILE,
                "offer",
                offer_h264_profiles,
                flush=True,
            )
    scrcpy_profile = (
        _probe_scrcpy_h264_profile_id(device_id) if not preferred_profile else None
    )
    if scrcpy_profile:
        scrcpy_profile = scrcpy_profile.lower()
        if scrcpy_profile in offer_h264_profiles:
            preferred_profile = scrcpy_profile
        else:
            print(
                "[webrtc] scrcpy profile mismatch",
                device_id,
                scrcpy_profile,
                "offer",
                offer_h264_profiles,
                flush=True,
            )
            scrcpy_profile = _probe_scrcpy_h264_profile_id(device_id, force=True)
            if scrcpy_profile:
                scrcpy_profile = scrcpy_profile.lower()
                if scrcpy_profile in offer_h264_profiles:
                    preferred_profile = scrcpy_profile
    else:
        print(
            "[webrtc] scrcpy profile not found",
            device_id,
            flush=True,
        )
    if not preferred_profile:
        preferred_profile = _choose_h264_profile_for_offer(payload.sdp, None)
    if preferred_profile:
        _ensure_h264_codec(preferred_profile)
    track = _select_webrtc_track(device_id, loop, "scrcpy")
    sender = pc.addTrack(track)
    if preferred_profile and isinstance(track, ScrcpyH264Track):
        sender_transceiver = next(
            (item for item in pc.getTransceivers() if item.sender == sender),
            None,
        )
        if sender_transceiver is not None:
            _apply_h264_preference(
                sender_transceiver, device_id, preferred_profile
            )

    @pc.on("connectionstatechange")
    async def on_connection_state_change() -> None:
        if pc.connectionState == "connected":
            if isinstance(track, ScrcpyH264Track):
                track.request_keyframe()
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            pcs.discard(pc)
            track.stop()

    await pc.setRemoteDescription(RTCSessionDescription(payload.sdp, payload.type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    selected_codec = None
    sender_transceiver = next(
        (item for item in pc.getTransceivers() if item.sender == sender),
        None,
    )
    if sender_transceiver is not None and sender_transceiver._codecs:
        selected_codec = sender_transceiver._codecs[0]
    if selected_codec is not None:
        print(
            "[webrtc] send codec",
            device_id,
            selected_codec.mimeType,
            selected_codec.parameters,
            flush=True,
        )
        if (
            isinstance(track, ScrcpyH264Track)
            and selected_codec.mimeType.lower() != "video/h264"
        ):
            print(
                "[webrtc] scrcpy codec mismatch",
                device_id,
                selected_codec.mimeType,
                flush=True,
            )
    await _wait_for_ice_gathering(pc)
    return JSONResponse(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run_id = _validate_run_id(run_id)
    run_dir = OUTPUTS_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="run not found")
    metadata = _read_json(run_dir / "run.json") or {"id": run_id}
    metadata["steps"] = _list_steps(run_dir)
    return JSONResponse(metadata)


@app.get("/api/runs/{run_id}/steps/{step_id}")
def get_step(run_id: str, step_id: str):
    run_id = _validate_run_id(run_id)
    if not RUN_ID_RE.match(step_id):
        raise HTTPException(status_code=400, detail="invalid step id")
    step_dir = OUTPUTS_DIR / run_id / step_id
    if not step_dir.exists():
        raise HTTPException(status_code=404, detail="step not found")
    return JSONResponse(_step_payload(run_id, step_id, step_dir))


@app.post("/api/run")
def start_run(payload: RunRequest):
    if payload.plan_verify not in ("llm", "none"):
        raise HTTPException(status_code=400, detail="invalid plan_verify value")
    if payload.max_steps <= 0:
        raise HTTPException(status_code=400, detail="max_steps must be positive")
    if payload.plan_max_steps <= 0:
        raise HTTPException(status_code=400, detail="plan_max_steps must be positive")
    if payload.device:
        _validate_device_id(payload.device)
    return JSONResponse(run_manager.start_run(payload))


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str):
    return JSONResponse(run_manager.stop_run(run_id))


app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
