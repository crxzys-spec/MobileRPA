import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..constants import OUTPUTS_DIR
from ..domains.device import DeviceCommand, DeviceSessionManager
from ..domains.run import RunService
from ..domains.stream import (
    list_devices as list_adb_devices,
    mjpeg_stream,
    shutdown as shutdown_stream,
    validate_device_id,
    webrtc_config as get_webrtc_config,
    webrtc_offer as create_webrtc_offer,
)
from ..domains.stream import service as stream_service
from ..settings import ServerSettings
from .schemas import (
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceInfo,
    DeviceQueueClearResponse,
    DeviceSessionCloseResponse,
    DeviceSessionStatus,
    RunMeta,
    RunLogResponse,
    RunRequest,
    RunStepDetail,
    RunStopResponse,
    WebRTCAnswer,
    WebRTCConfigResponse,
    WebRTCOffer,
)

router = APIRouter()

SETTINGS = ServerSettings()
run_service = RunService(OUTPUTS_DIR)
device_manager = DeviceSessionManager(
    adb_path=stream_service.ADB_PATH,
    ime_id=SETTINGS.adb_ime_id,
    restore_ime=SETTINGS.adb_ime_restore,
)


async def shutdown_event() -> None:
    shutdown_stream()
    device_manager.shutdown()


@router.get("/api/runs", response_model=list[RunMeta])
def list_runs():
    return run_service.list_runs()


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


@router.get("/api/runs/{run_id}", response_model=RunMeta)
def get_run(run_id: str):
    return run_service.get_run(run_id)


@router.get("/api/runs/{run_id}/log", response_model=RunLogResponse)
def get_run_log(run_id: str, limit: int = 200):
    return run_service.get_run_log(run_id, limit=limit)


@router.get("/api/runs/{run_id}/log/stream")
async def stream_run_log(
    run_id: str, request: Request, from_line: int = 0, interval: float = 0.5
):
    run_service.get_run_log_path(run_id)

    async def event_stream():
        async for payload in run_service.stream_run_log(
            run_id, start_line=from_line, interval=interval
        ):
            if await request.is_disconnected():
                break
            data = json.dumps(payload, ensure_ascii=False)
            yield "event: log\ndata: {}\n\n".format(data)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.get("/api/runs/{run_id}/steps/{step_id}", response_model=RunStepDetail)
def get_step(run_id: str, step_id: str):
    return run_service.get_step(run_id, step_id)


@router.post("/api/run", response_model=RunMeta)
def start_run(payload: RunRequest):
    if payload.device:
        validate_device_id(payload.device)
    return run_service.start_run(payload)


@router.post("/api/runs/{run_id}/stop", response_model=RunStopResponse)
def stop_run(run_id: str):
    return run_service.stop_run(run_id)
