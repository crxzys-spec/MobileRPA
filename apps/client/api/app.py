import asyncio
import contextlib
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from mrpa.domains.device import DeviceCommand, DeviceSessionManager
from infra.scrcpy import ScrcpyControlConfig
from mrpa.domains.stream import (
    list_devices as list_adb_devices,
    mjpeg_stream,
    set_scrcpy_session_manager,
    shutdown_async as shutdown_stream,
    validate_device_id,
    webrtc_config as get_webrtc_config,
    webrtc_offer as create_webrtc_offer,
)
from mrpa.domains.stream import service as stream_service
from mrpa.domains.stream.scrcpy_sessions import (
    ScrcpySessionConfig,
    ScrcpySessionManager,
    ScrcpySessionStatus,
)
from mrpa.settings import ServerSettings

from .schemas import (
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceInfo,
    DeviceQueueClearResponse,
    DeviceSessionCloseResponse,
    DeviceSessionStatus,
    ScrcpySessionConfigRequest,
    ScrcpySessionStatusResponse,
    WebRTCAnswer,
    WebRTCConfigResponse,
    WebRTCOffer,
)

router = APIRouter()

SETTINGS = ServerSettings()
scrcpy_config = None
if (SETTINGS.input_driver or "adb") == "scrcpy":
    scrcpy_config = ScrcpyControlConfig(
        adb_path=stream_service.ADB_PATH,
        server_path=stream_service.SCRCPY_SERVER_PATH,
        server_version=SETTINGS.scrcpy_server_version,
        log_level=SETTINGS.scrcpy_log_level,
        port=SETTINGS.scrcpy_control_port,
        connect_timeout=SETTINGS.scrcpy_connect_timeout,
        start_delay_ms=SETTINGS.scrcpy_start_delay_ms,
    )
device_manager = DeviceSessionManager(
    adb_path=stream_service.ADB_PATH,
    ime_id=SETTINGS.adb_ime_id,
    restore_ime=SETTINGS.adb_ime_restore,
    input_driver=SETTINGS.input_driver or "adb",
    scrcpy_config=scrcpy_config,
    input_allow_fallback=SETTINGS.input_allow_fallback,
)
scrcpy_sessions = ScrcpySessionManager()
set_scrcpy_session_manager(scrcpy_sessions)


async def shutdown_event() -> None:
    with contextlib.suppress(Exception):
        asyncio.create_task(shutdown_stream())
    threading.Thread(target=device_manager.shutdown, daemon=True).start()
    threading.Thread(target=scrcpy_sessions.stop_all, daemon=True).start()


def _merge_scrcpy_config(
    device_id: str, payload: Optional[ScrcpySessionConfigRequest]
) -> ScrcpySessionConfig:
    base = scrcpy_sessions.get_config(device_id)
    data = base.as_dict()
    if payload:
        updates = payload.model_dump(exclude_none=True)
        data.update(updates)
    return ScrcpySessionConfig(**data)


def _status_for_device(device_id: str) -> ScrcpySessionStatus:
    session = scrcpy_sessions.get_session(device_id)
    if session:
        return session.status()
    return ScrcpySessionStatus(
        device_id=device_id,
        status="stopped",
        config=scrcpy_sessions.get_config(device_id),
    )


@router.get("/api/devices", response_model=list[DeviceInfo])
def list_devices():
    return list_adb_devices()


@router.get("/api/device/sessions", response_model=list[DeviceSessionStatus])
def list_device_sessions():
    return device_manager.list_sessions()


@router.get("/api/device/{device_id}/session", response_model=DeviceSessionStatus)
def get_device_session(device_id: str):
    device_id = validate_device_id(device_id)
    session = device_manager.get_session(device_id)
    if not session:
        raise HTTPException(status_code=404, detail="device session not found")
    return session.status_dict()


@router.get(
    "/api/stream/sessions",
    response_model=list[ScrcpySessionStatusResponse],
)
def list_stream_sessions():
    return [status.as_dict() for status in scrcpy_sessions.list_sessions()]


@router.get(
    "/api/stream/{device_id}/session",
    response_model=ScrcpySessionStatusResponse,
)
def get_stream_session(device_id: str):
    device_id = validate_device_id(device_id)
    return _status_for_device(device_id).as_dict()


@router.post(
    "/api/stream/{device_id}/start",
    response_model=ScrcpySessionStatusResponse,
)
def start_stream_session(
    device_id: str, payload: Optional[ScrcpySessionConfigRequest] = None
):
    device_id = validate_device_id(device_id)
    config = _merge_scrcpy_config(device_id, payload)
    status = scrcpy_sessions.start(device_id, config)
    return status.as_dict()


@router.post(
    "/api/stream/{device_id}/restart",
    response_model=ScrcpySessionStatusResponse,
)
def restart_stream_session(
    device_id: str, payload: Optional[ScrcpySessionConfigRequest] = None
):
    device_id = validate_device_id(device_id)
    config = _merge_scrcpy_config(device_id, payload)
    status = scrcpy_sessions.restart(device_id, config)
    return status.as_dict()


@router.post(
    "/api/stream/{device_id}/stop",
    response_model=ScrcpySessionStatusResponse,
)
def stop_stream_session(device_id: str):
    device_id = validate_device_id(device_id)
    status = scrcpy_sessions.stop(device_id)
    return status.as_dict()


@router.post(
    "/api/stream/{device_id}/config",
    response_model=ScrcpySessionStatusResponse,
)
def update_stream_config(
    device_id: str, payload: ScrcpySessionConfigRequest
):
    device_id = validate_device_id(device_id)
    config = _merge_scrcpy_config(device_id, payload)
    session = scrcpy_sessions.get_session(device_id)
    if session:
        status = session.status()
        if status.status in ("running", "starting"):
            return scrcpy_sessions.restart(device_id, config).as_dict()
    scrcpy_sessions.set_config(device_id, config)
    return _status_for_device(device_id).as_dict()


@router.post(
    "/api/device/{device_id}/commands", response_model=DeviceCommandResponse
)
def enqueue_device_command(device_id: str, payload: DeviceCommandRequest):
    device_id = validate_device_id(device_id)
    command = DeviceCommand(
        command_type=payload.type,
        payload=payload.model_dump(exclude={"type"}, exclude_none=True),
    )
    result = device_manager.enqueue(device_id, command)
    return result.to_dict()


@router.get(
    "/api/device/{device_id}/commands", response_model=list[DeviceCommandResponse]
)
def list_device_commands(device_id: str, limit: int = 50):
    device_id = validate_device_id(device_id)
    return device_manager.list_commands(device_id, limit=limit)


@router.post(
    "/api/device/{device_id}/queue/clear",
    response_model=DeviceQueueClearResponse,
)
def clear_device_queue(device_id: str):
    device_id = validate_device_id(device_id)
    drained = device_manager.clear_queue(device_id)
    return {"device_id": device_id, "drained": drained}


@router.post(
    "/api/device/{device_id}/session/close",
    response_model=DeviceSessionCloseResponse,
)
def close_device_session(device_id: str):
    device_id = validate_device_id(device_id)
    closed = device_manager.close(device_id)
    if not closed:
        raise HTTPException(status_code=404, detail="device session not found")
    return {"device_id": device_id, "closed": True}


@router.get("/api/stream/{device_id}.mjpg")
def stream_device(device_id: str):
    generator = mjpeg_stream(device_id)
    return StreamingResponse(
        generator,
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/webrtc/config", response_model=WebRTCConfigResponse)
def webrtc_config():
    config = dict(get_webrtc_config() or {})
    config["client_mode"] = "client"
    config["mjpeg_available"] = True
    config["input_driver"] = SETTINGS.input_driver or "adb"
    config["input_allow_fallback"] = SETTINGS.input_allow_fallback
    return config


@router.post("/api/webrtc/offer", response_model=WebRTCAnswer)
async def webrtc_offer(payload: WebRTCOffer):
    asyncio.create_task(
        asyncio.to_thread(device_manager.warmup_control, payload.device_id)
    )
    answer = await create_webrtc_offer(payload)
    return {"sdp": answer.sdp, "type": answer.type}
