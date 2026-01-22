from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class DeviceCommandRequest(BaseModel):
    type: str = Field(min_length=1)
    x: Optional[int] = None
    y: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    x1: Optional[int] = None
    y1: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    duration_ms: Optional[int] = None
    keycode: Optional[str] = None
    text: Optional[str] = None
    package: Optional[str] = None
    activity: Optional[str] = None
    wait_ms: Optional[int] = None

    @model_validator(mode="after")
    def _validate(self):
        command_type = self.type
        if command_type in ("tap", "touch_down", "touch_move", "touch_up"):
            if self.x is None or self.y is None:
                raise ValueError("{} requires x and y".format(command_type))
            return self
        if command_type == "swipe":
            if None in (self.x1, self.y1, self.x2, self.y2):
                raise ValueError("swipe requires x1, y1, x2, y2")
            return self
        if command_type == "keyevent":
            if self.keycode is None:
                raise ValueError("keyevent requires keycode")
            return self
        if command_type == "input_text":
            if self.text is None:
                raise ValueError("input_text requires text")
            return self
        if command_type == "start_app":
            if not self.package:
                raise ValueError("start_app requires package")
            return self
        if command_type in ("back", "home", "recent", "wait"):
            return self
        raise ValueError("unsupported command type")


class RunStepSummary(BaseModel):
    id: str
    decision: Optional[Dict[str, Any]] = None
    has_screen: Optional[bool] = None
    updated_time: Optional[float] = None

    model_config = ConfigDict(extra="allow")


class RunMeta(BaseModel):
    id: str
    goal: Optional[str] = None
    status: Optional[str] = None
    device_id: Optional[str] = None
    device: Optional[str] = None
    updated_time: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    steps: Optional[List[RunStepSummary]] = None

    model_config = ConfigDict(extra="allow")


class RunStepDetail(RunStepSummary):
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    response: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    ocr_payload: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    screen_url: Optional[str] = None
    step_screen_url: Optional[str] = None
    step_after_url: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class RunStopResponse(BaseModel):
    id: str
    status: str


class RunLogResponse(BaseModel):
    run_id: str
    text: str
    lines: int
    total_lines: int
    truncated: bool
    updated_time: Optional[float] = None
    log_path: Optional[str] = None


class DeviceInfo(BaseModel):
    id: str
    status: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class DeviceCommandResponse(BaseModel):
    id: str
    type: str
    status: str
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    payload: Dict[str, Any]

    model_config = ConfigDict(extra="allow")


class DeviceSessionStatus(BaseModel):
    device_id: str
    status: str
    pending: int
    current_command_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: float
    updated_at: float

    model_config = ConfigDict(extra="allow")


class DeviceQueueClearResponse(BaseModel):
    device_id: str
    drained: int


class DeviceSessionCloseResponse(BaseModel):
    device_id: str
    closed: bool


class WebRTCConfigResponse(BaseModel):
    ice_servers: List[str] = Field(default_factory=list)
    mjpeg_available: bool = True
    client_mode: Optional[str] = None
    input_driver: Optional[str] = None
    input_allow_fallback: bool = True


class WebRTCAnswer(BaseModel):
    sdp: str
    type: str


class ScrcpySessionConfigRequest(BaseModel):
    video: Optional[bool] = None
    audio: Optional[bool] = None
    control: Optional[bool] = None
    max_fps: Optional[int] = None
    video_bit_rate: Optional[int] = None
    max_size: Optional[int] = None
    video_codec_options: Optional[str] = None
    audio_codec: Optional[str] = None
    log_level: Optional[str] = None


class ScrcpySessionConfig(BaseModel):
    video: bool
    audio: bool
    control: bool
    max_fps: int
    video_bit_rate: int
    max_size: int
    video_codec_options: str
    audio_codec: str
    log_level: str

    model_config = ConfigDict(extra="allow")


class ScrcpySessionStatusResponse(BaseModel):
    device_id: str
    status: str
    config: ScrcpySessionConfig
    started_at: Optional[float] = None
    updated_at: float
    last_error: Optional[str] = None
    port: Optional[int] = None
    scid: Optional[str] = None

    model_config = ConfigDict(extra="allow")
