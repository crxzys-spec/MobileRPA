from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from mrpa.domains.device import DeviceCommand, DeviceSessionManager
from mrpa.domains.stream import (
    list_devices as list_adb_devices,
    mjpeg_stream,
    shutdown as shutdown_stream,
    validate_device_id,
    webrtc_config as get_webrtc_config,
    webrtc_offer as create_webrtc_offer,
)
from mrpa.domains.stream import service as stream_service
from mrpa.settings import ServerSettings

from .schemas import (
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceInfo,
    DeviceQueueClearResponse,
    DeviceSessionCloseResponse,
    DeviceSessionStatus,
    WebRTCAnswer,
    WebRTCConfigResponse,
    WebRTCOffer,
)

router = APIRouter()

SETTINGS = ServerSettings()
device_manager = DeviceSessionManager(
    adb_path=stream_service.ADB_PATH,
    ime_id=SETTINGS.adb_ime_id,
    restore_ime=SETTINGS.adb_ime_restore,
)


async def shutdown_event() -> None:
    shutdown_stream()
    device_manager.shutdown()


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
    return get_webrtc_config()


@router.post("/api/webrtc/offer", response_model=WebRTCAnswer)
async def webrtc_offer(payload: WebRTCOffer):
    answer = await create_webrtc_offer(payload)
    return {"sdp": answer.sdp, "type": answer.type}
