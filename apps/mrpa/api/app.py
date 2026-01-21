import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import StreamingResponse

from infra.ws import JsonWsServer
from ..constants import OUTPUTS_DIR
from ..domains.client import ClientApi, ClientRegistry
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
CLIENT_MODE = SETTINGS.client_mode or "local"
client_api = None
client_registry = None
ws_server = JsonWsServer(
    token=SETTINGS.client_token,
    trace=SETTINGS.client_ws_trace,
)
device_manager = None
_sweeper_task = None
if CLIENT_MODE == "pull":
    if not SETTINGS.client_url:
        raise RuntimeError("MRPA_CLIENT_URL is required for pull mode")
    client_api = ClientApi(
        SETTINGS.client_url, timeout=SETTINGS.client_timeout
    )
elif CLIENT_MODE == "push":
    client_registry = ClientRegistry()
else:
    device_manager = DeviceSessionManager(
        adb_path=stream_service.ADB_PATH,
        ime_id=SETTINGS.adb_ime_id,
        restore_ime=SETTINGS.adb_ime_restore,
    )


async def shutdown_event() -> None:
    global _sweeper_task
    if _sweeper_task:
        _sweeper_task.cancel()
        _sweeper_task = None
    if client_api or client_registry:
        return
    shutdown_stream()
    if device_manager:
        device_manager.shutdown()


@router.get("/api/runs", response_model=list[RunMeta])
def list_runs():
    return run_service.list_runs()


@router.get("/api/devices", response_model=list[DeviceInfo])
def list_devices():
    if client_api:
        return client_api.list_devices()
    if client_registry:
        return client_registry.list_devices(
            inactive_after=SETTINGS.client_inactive_seconds
        )
    return list_adb_devices()


@router.get("/api/device/sessions", response_model=list[DeviceSessionStatus])
def list_device_sessions():
    if client_api:
        return client_api.list_device_sessions()
    if client_registry:
        return client_registry.list_sessions(
            inactive_after=SETTINGS.client_inactive_seconds
        )
    return device_manager.list_sessions()


@router.get("/api/device/{device_id}/session", response_model=DeviceSessionStatus)
def get_device_session(device_id: str):
    device_id = validate_device_id(device_id)
    if client_api:
        return client_api.get_device_session(device_id)
    if client_registry:
        session = client_registry.get_session(
            device_id, inactive_after=SETTINGS.client_inactive_seconds
        )
        if not session:
            raise HTTPException(status_code=404, detail="device session not found")
        return session
    session = device_manager.get_session(device_id)
    if not session:
        raise HTTPException(status_code=404, detail="device session not found")
    return session.status_dict()


@router.post(
    "/api/device/{device_id}/commands", response_model=DeviceCommandResponse
)
async def enqueue_device_command(device_id: str, payload: DeviceCommandRequest):
    device_id = validate_device_id(device_id)
    if client_api:
        return client_api.enqueue_device_command(
            device_id, payload.model_dump()
        )
    if client_registry:
        command_payload = payload.model_dump(exclude_none=True)
        command = client_registry.enqueue_command(device_id, command_payload)
        command_payload["id"] = command["id"]
        await client_registry.send_to_device(
            device_id,
            {
                "type": "command",
                "device_id": device_id,
                "command": command_payload,
            },
        )
        return command
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
    if client_api:
        return client_api.list_device_commands(device_id, limit=limit)
    if client_registry:
        return client_registry.list_commands(device_id, limit=limit)
    return device_manager.list_commands(device_id, limit=limit)


@router.post(
    "/api/device/{device_id}/queue/clear",
    response_model=DeviceQueueClearResponse,
)
async def clear_device_queue(device_id: str):
    device_id = validate_device_id(device_id)
    if client_api:
        return client_api.clear_device_queue(device_id)
    if client_registry:
        result = await client_registry.request_device(
            device_id,
            {"type": "queue_clear", "device_id": device_id},
            timeout=SETTINGS.client_timeout,
        )
        if result.get("error"):
            raise HTTPException(status_code=502, detail=result.get("error"))
        return result
    drained = device_manager.clear_queue(device_id)
    return {"device_id": device_id, "drained": drained}


@router.post(
    "/api/device/{device_id}/session/close",
    response_model=DeviceSessionCloseResponse,
)
async def close_device_session(device_id: str):
    device_id = validate_device_id(device_id)
    if client_api:
        return client_api.close_device_session(device_id)
    if client_registry:
        result = await client_registry.request_device(
            device_id,
            {"type": "session_close", "device_id": device_id},
            timeout=SETTINGS.client_timeout,
        )
        if result.get("error"):
            raise HTTPException(status_code=502, detail=result.get("error"))
        return result
    closed = device_manager.close(device_id)
    if not closed:
        raise HTTPException(status_code=404, detail="device session not found")
    return {"device_id": device_id, "closed": True}


@router.get("/api/stream/{device_id}.mjpg")
def stream_device(device_id: str):
    if client_api:
        content_type, generator = client_api.stream_mjpeg(device_id)
        return StreamingResponse(generator, media_type=content_type)
    if client_registry:
        raise HTTPException(
            status_code=501,
            detail="mjpeg stream not available in push mode",
        )
    generator = mjpeg_stream(device_id)
    return StreamingResponse(
        generator,
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/webrtc/config", response_model=WebRTCConfigResponse)
def webrtc_config():
    if client_api:
        return client_api.webrtc_config()
    return get_webrtc_config()


@router.post("/api/webrtc/offer", response_model=WebRTCAnswer)
async def webrtc_offer(payload: WebRTCOffer):
    if client_api:
        return await client_api.webrtc_offer(payload.model_dump())
    if client_registry:
        response = await client_registry.request_device(
            payload.device_id,
            {
                "type": "webrtc_offer",
                "device_id": payload.device_id,
                "sdp": payload.sdp,
                "sdp_type": payload.type,
            },
            timeout=SETTINGS.client_timeout,
        )
        if response.get("error"):
            raise HTTPException(status_code=502, detail=response.get("error"))
        return {
            "sdp": response.get("sdp"),
            "type": response.get("sdp_type") or response.get("type"),
        }
    answer = await create_webrtc_offer(payload)
    return {"sdp": answer.sdp, "type": answer.type}


@router.websocket(SETTINGS.client_ws_path)
async def client_socket(websocket: WebSocket):
    if not client_registry:
        await websocket.close(code=1008)
        return
    client_id = None
    async def on_message(data: dict) -> None:
        nonlocal client_id
        msg_type = data.get("type")
        if msg_type == "register":
            client_id = str(data.get("client_id") or "").strip()
            if not client_id:
                client_id = "client-{}".format(int(time.time()))
            client_registry.register(
                client_id,
                websocket,
                data.get("devices") or [],
                data.get("sessions") or [],
            )
            return
        if not client_id:
            return
        client_registry.touch(client_id)
        if msg_type == "devices_update":
            client_registry.update_devices(
                client_id, data.get("devices") or []
            )
            return
        if msg_type == "sessions_update":
            client_registry.update_sessions(
                client_id, data.get("sessions") or []
            )
            return
        if msg_type == "session_update":
            session = data.get("session") or {}
            client_registry.update_session(client_id, session)
            return
        if msg_type == "command_update":
            command = data.get("command") or {}
            device_id = data.get("device_id") or command.get("device_id")
            if device_id:
                client_registry.update_command(device_id, command)
            return
        if msg_type in (
            "queue_clear_result",
            "session_close_result",
            "webrtc_answer",
        ):
            request_id = data.get("request_id")
            if request_id:
                client_registry.resolve_pending(request_id, data)

    async def on_disconnect() -> None:
        if client_id:
            client_registry.mark_disconnected(client_id)

    await ws_server.handle(
        websocket,
        on_message,
        on_disconnect=on_disconnect,
    )


async def startup_event() -> None:
    global _sweeper_task
    if not client_registry:
        return
    if SETTINGS.client_sweep_interval <= 0:
        return

    async def sweeper() -> None:
        while True:
            client_registry.sweep(
                inactive_after=SETTINGS.client_inactive_seconds,
                evict_after=SETTINGS.client_evict_seconds,
            )
            await asyncio.sleep(SETTINGS.client_sweep_interval)

    _sweeper_task = asyncio.create_task(sweeper())


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
