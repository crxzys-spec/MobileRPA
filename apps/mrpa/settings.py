import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import dotenv_values
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infra.llm import LlmConfig

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILES = (ROOT_DIR / ".env", ROOT_DIR / ".env.example")


def _read_env_values() -> dict:
    values = {}
    for path in ENV_FILES:
        if not path.exists():
            continue
        values.update(dotenv_values(path))
    values.update(os.environ)
    return values


class OCRSettings(BaseModel):
    provider: str = Field(
        default="remote",
        validation_alias=AliasChoices("OCR_PROVIDER", "MRPA_OCR_PROVIDER"),
    )
    remote_url: str = Field(
        default="http://127.0.0.1:8001/ocr",
        validation_alias=AliasChoices("OCR_REMOTE_URL", "MRPA_OCR_REMOTE_URL"),
    )
    timeout: float = Field(
        default=30.0,
        validation_alias=AliasChoices("OCR_REMOTE_TIMEOUT", "MRPA_OCR_TIMEOUT"),
    )
    api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OCR_API_KEY", "MRPA_OCR_API_KEY"),
    )
    device: Optional[str] = Field(
        default="auto",
        validation_alias=AliasChoices("OCR_DEVICE", "MRPA_OCR_DEVICE"),
    )

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class LLMSettings(BaseModel):
    provider: str = Field(
        default="openai",
        validation_alias=AliasChoices("LLM_PROVIDER", "MRPA_LLM_PROVIDER"),
    )
    api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "MRPA_LLM_API_KEY"),
    )
    model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("LLM_MODEL", "MRPA_LLM_MODEL"),
    )
    temperature: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_TEMPERATURE", "MRPA_LLM_TEMPERATURE"),
    )
    timeout: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT", "MRPA_LLM_TIMEOUT"),
    )
    base_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_BASE_URL", "MRPA_LLM_BASE_URL"),
    )
    azure_endpoint: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "AZURE_OPENAI_ENDPOINT", "MRPA_AZURE_OPENAI_ENDPOINT"
        ),
    )
    azure_deployment: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "AZURE_OPENAI_DEPLOYMENT", "MRPA_AZURE_OPENAI_DEPLOYMENT"
        ),
    )
    azure_api_version: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "AZURE_OPENAI_API_VERSION", "MRPA_AZURE_OPENAI_API_VERSION"
        ),
    )
    anthropic_version: Optional[str] = Field(
        default="2023-06-01",
        validation_alias=AliasChoices("ANTHROPIC_VERSION", "MRPA_ANTHROPIC_VERSION"),
    )
    max_tokens: int = Field(
        default=1024,
        validation_alias=AliasChoices(
            "LLM_MAX_TOKENS",
            "MRPA_LLM_MAX_TOKENS",
            "ANTHROPIC_MAX_TOKENS",
            "MRPA_ANTHROPIC_MAX_TOKENS",
        ),
    )

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("temperature", mode="before")
    @classmethod
    def _parse_temperature(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ClientSettings(BaseSettings):
    adb_path: str = Field(
        default="adb",
        validation_alias=AliasChoices("ADB_PATH", "MRPA_ADB_PATH"),
    )
    device_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DEVICE_ID", "MRPA_DEVICE_ID"),
    )
    adb_ime_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ADB_IME_ID", "MRPA_ADB_IME_ID"),
    )
    adb_ime_restore: bool = Field(
        default=True,
        validation_alias=AliasChoices("ADB_IME_RESTORE", "MRPA_ADB_IME_RESTORE"),
    )
    plan_image_max_side: int = Field(
        default=720,
        validation_alias=AliasChoices(
            "PLAN_IMAGE_MAX_SIDE",
            "MRPA_PLAN_IMAGE_MAX_SIDE",
        ),
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "MRPA_OPENAI_API_KEY"),
    )
    openai_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("OPENAI_MODEL", "MRPA_OPENAI_MODEL"),
    )
    openai_temperature: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_TEMPERATURE", "MRPA_OPENAI_TEMPERATURE"),
    )
    llm: LLMSettings = LLMSettings()
    ocr: OCRSettings = OCRSettings()

    model_config = SettingsConfigDict(
        env_file=[str(path) for path in ENV_FILES],
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("openai_temperature", mode="before")
    @classmethod
    def _parse_openai_temperature(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (
            env_settings,
            dotenv_settings,
            _legacy_env_settings,
            init_settings,
            file_secret_settings,
        )


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(path) for path in ENV_FILES],
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    adb_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_ADB_PATH", "ADB_PATH"),
    )
    adb_ime_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_ADB_IME_ID", "ADB_IME_ID"),
    )
    adb_ime_restore: bool = Field(
        default=True,
        validation_alias=AliasChoices("MRPA_ADB_IME_RESTORE", "ADB_IME_RESTORE"),
    )
    ffmpeg_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_FFMPEG_PATH", "FFMPEG_PATH"),
    )
    scrcpy_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_SCRCPY_PATH", "SCRCPY_PATH"),
    )
    scrcpy_server_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_SCRCPY_SERVER_PATH", "SCRCPY_SERVER_PATH"),
    )

    serve_studio: bool = Field(
        default=True,
        validation_alias=AliasChoices("MRPA_SERVE_STUDIO", "SERVE_STUDIO"),
    )
    cors_origins: str = Field(
        default="",
        validation_alias=AliasChoices("MRPA_CORS_ORIGINS", "CORS_ORIGINS"),
    )
    client_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_CLIENT_URL", "CLIENT_URL"),
    )
    client_timeout: float = Field(
        default=10.0,
        validation_alias=AliasChoices("MRPA_CLIENT_TIMEOUT", "CLIENT_TIMEOUT"),
    )
    client_mode: str = Field(
        default="local",
        validation_alias=AliasChoices("MRPA_CLIENT_MODE", "CLIENT_MODE"),
    )
    client_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_CLIENT_TOKEN", "CLIENT_TOKEN"),
    )
    client_ws_path: str = Field(
        default="/ws/client",
        validation_alias=AliasChoices("MRPA_CLIENT_WS_PATH", "CLIENT_WS_PATH"),
    )
    client_ws_trace: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "MRPA_CLIENT_WS_TRACE", "CLIENT_WS_TRACE"
        ),
    )
    client_inactive_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "MRPA_CLIENT_INACTIVE_SEC", "CLIENT_INACTIVE_SEC"
        ),
    )
    client_evict_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "MRPA_CLIENT_EVICT_SEC", "CLIENT_EVICT_SEC"
        ),
    )
    client_sweep_interval: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "MRPA_CLIENT_SWEEP_INTERVAL", "CLIENT_SWEEP_INTERVAL"
        ),
    )

    stream_fps: int = Field(default=30, validation_alias="MRPA_STREAM_FPS")
    stream_scale: int = Field(default=0, validation_alias="MRPA_STREAM_SCALE")
    stream_bitrate: int = Field(
        default=16_000_000, validation_alias="MRPA_STREAM_BITRATE"
    )
    stream_quality: int = Field(default=6, validation_alias="MRPA_STREAM_QUALITY")
    stream_segment_seconds: int = Field(
        default=180, validation_alias="MRPA_STREAM_SEGMENT_SECONDS"
    )
    stream_analyze_us: int = Field(
        default=1_000_000, validation_alias="MRPA_STREAM_ANALYZE_US"
    )
    stream_probesize: int = Field(
        default=1_000_000, validation_alias="MRPA_STREAM_PROBESIZE"
    )
    stream_driver: str = Field(
        default="scrcpy", validation_alias="MRPA_STREAM_DRIVER"
    )
    stream_detection_timeout: int = Field(
        default=8, validation_alias="MRPA_STREAM_DETECTION_TIMEOUT"
    )

    webrtc_source: str = Field(default="scrcpy", validation_alias="MRPA_WEBRTC_SOURCE")
    scrcpy_server_version: str = Field(
        default="3.3.4", validation_alias="MRPA_SCRCPY_SERVER_VERSION"
    )
    scrcpy_server_port: int = Field(
        default=27183, validation_alias="MRPA_SCRCPY_PORT"
    )
    scrcpy_connect_timeout: int = Field(
        default=6, validation_alias="MRPA_SCRCPY_TIMEOUT"
    )
    scrcpy_read_timeout: int = Field(
        default=6, validation_alias="MRPA_SCRCPY_READ_TIMEOUT"
    )
    scrcpy_meta_retries: int = Field(
        default=6, validation_alias="MRPA_SCRCPY_META_RETRIES"
    )
    scrcpy_start_delay_ms: int = Field(
        default=200, validation_alias="MRPA_SCRCPY_START_DELAY_MS"
    )
    scrcpy_video_options: str = Field(
        default="", validation_alias="MRPA_SCRCPY_VIDEO_OPTIONS"
    )
    scrcpy_log_level: str = Field(
        default="", validation_alias="MRPA_SCRCPY_LOG_LEVEL"
    )
    webrtc_ice: str = Field(default="", validation_alias="MRPA_WEBRTC_ICE")
    forced_h264_profile: str = Field(
        default="", validation_alias="MRPA_H264_PROFILE"
    )

    @field_validator(
        "adb_path",
        "ffmpeg_path",
        "scrcpy_path",
        "scrcpy_server_path",
        "scrcpy_server_version",
        "scrcpy_video_options",
        "webrtc_ice",
        "cors_origins",
        "client_url",
        "client_token",
        "client_ws_path",
        mode="before",
    )
    @classmethod
    def _strip_optional(cls, value):
        if value is None:
            return None
        return str(value).strip()

    @field_validator(
        "stream_driver",
        "webrtc_source",
        "scrcpy_log_level",
        "forced_h264_profile",
        "client_mode",
        mode="before",
    )
    @classmethod
    def _strip_lower(cls, value):
        if value is None:
            return ""
        return str(value).strip().lower()

    @property
    def webrtc_ice_urls(self) -> List[str]:
        if not self.webrtc_ice:
            return []
        return [item.strip() for item in self.webrtc_ice.split(",") if item.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        if not self.cors_origins:
            return []
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class OcrRuntimeConfig:
    provider: str
    remote_url: str
    timeout: float
    api_key: Optional[str]
    remote_device: Optional[str]
    use_gpu: bool


def build_llm_config(
    settings: "ClientSettings",
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
) -> LlmConfig:
    llm_settings = settings.llm
    provider = (llm_settings.provider or "openai").strip().lower()
    resolved_model = model or llm_settings.model or settings.openai_model or "gpt-4o"
    resolved_key = api_key or llm_settings.api_key or settings.openai_api_key
    resolved_temp = temperature if temperature is not None else llm_settings.temperature
    if resolved_temp is None:
        resolved_temp = settings.openai_temperature
    return LlmConfig(
        provider=provider,
        api_key=resolved_key,
        model=resolved_model,
        temperature=resolved_temp,
        timeout=llm_settings.timeout,
        base_url=llm_settings.base_url,
        azure_endpoint=llm_settings.azure_endpoint,
        azure_deployment=llm_settings.azure_deployment,
        azure_api_version=llm_settings.azure_api_version,
        anthropic_version=llm_settings.anthropic_version,
        max_tokens=llm_settings.max_tokens,
    )


def resolve_ocr_runtime(settings: "ClientSettings") -> OcrRuntimeConfig:
    ocr_settings = settings.ocr
    provider = (ocr_settings.provider or "remote").strip().lower()
    device_raw = ocr_settings.device
    device = (device_raw or "auto").strip().lower()
    use_gpu = provider == "local" and device in ("gpu", "cuda")
    return OcrRuntimeConfig(
        provider=provider,
        remote_url=ocr_settings.remote_url,
        timeout=ocr_settings.timeout,
        api_key=ocr_settings.api_key,
        remote_device=device_raw,
        use_gpu=use_gpu,
    )


def load_settings(config_path: Optional[str]) -> ClientSettings:
    data = {}
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError("config not found: {}".format(path))
        data = _load_json(path)
    return ClientSettings(**data)


def _legacy_env_settings(_settings: Optional[BaseSettings] = None, *_args, **_kwargs) -> dict:
    env = _read_env_values()
    data = {}
    ocr = {}
    env_map = {
        "OCR_PROVIDER": "provider",
        "MRPA_OCR_PROVIDER": "provider",
        "OCR_REMOTE_URL": "remote_url",
        "MRPA_OCR_REMOTE_URL": "remote_url",
        "OCR_REMOTE_TIMEOUT": "timeout",
        "MRPA_OCR_TIMEOUT": "timeout",
        "OCR_API_KEY": "api_key",
        "MRPA_OCR_API_KEY": "api_key",
        "OCR_DEVICE": "device",
        "MRPA_OCR_DEVICE": "device",
    }
    for env_key, field in env_map.items():
        value = env.get(env_key)
        if value in (None, ""):
            continue
        if field == "timeout":
            try:
                value = float(value)
            except ValueError:
                continue
        ocr[field] = value
    if ocr:
        data["ocr"] = ocr
    llm = {}
    llm_map = {
        "LLM_PROVIDER": "provider",
        "MRPA_LLM_PROVIDER": "provider",
        "LLM_API_KEY": "api_key",
        "MRPA_LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
        "MRPA_LLM_MODEL": "model",
        "LLM_TEMPERATURE": "temperature",
        "MRPA_LLM_TEMPERATURE": "temperature",
        "LLM_TIMEOUT": "timeout",
        "MRPA_LLM_TIMEOUT": "timeout",
        "LLM_BASE_URL": "base_url",
        "MRPA_LLM_BASE_URL": "base_url",
        "AZURE_OPENAI_ENDPOINT": "azure_endpoint",
        "MRPA_AZURE_OPENAI_ENDPOINT": "azure_endpoint",
        "AZURE_OPENAI_DEPLOYMENT": "azure_deployment",
        "MRPA_AZURE_OPENAI_DEPLOYMENT": "azure_deployment",
        "AZURE_OPENAI_API_VERSION": "azure_api_version",
        "MRPA_AZURE_OPENAI_API_VERSION": "azure_api_version",
        "ANTHROPIC_VERSION": "anthropic_version",
        "MRPA_ANTHROPIC_VERSION": "anthropic_version",
        "LLM_MAX_TOKENS": "max_tokens",
        "MRPA_LLM_MAX_TOKENS": "max_tokens",
        "ANTHROPIC_MAX_TOKENS": "max_tokens",
        "MRPA_ANTHROPIC_MAX_TOKENS": "max_tokens",
    }
    for env_key, field in llm_map.items():
        value = env.get(env_key)
        if value in (None, ""):
            continue
        if field == "timeout":
            try:
                value = float(value)
            except ValueError:
                continue
        if field == "max_tokens":
            try:
                value = int(value)
            except ValueError:
                continue
        llm[field] = value
    if llm:
        data["llm"] = llm
    return data


def _load_json(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))
