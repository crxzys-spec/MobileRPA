from pathlib import Path
from typing import List, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILES = (ROOT_DIR / ".env", ROOT_DIR / ".env.example")


class StudioSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(path) for path in ENV_FILES],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adb_path: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MRPA_ADB_PATH", "ADB_PATH"),
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
