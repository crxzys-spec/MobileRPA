from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILES = (ROOT_DIR / ".env", ROOT_DIR / ".env.example")


class ClientServiceSettings(BaseSettings):
    mrpa_ws_url: str = Field(
        default="ws://127.0.0.1:8020/ws/client",
        validation_alias=AliasChoices("CLIENT_MRPA_WS", "MRPA_CLIENT_WS"),
    )
    client_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("CLIENT_ID", "MRPA_CLIENT_ID"),
    )
    token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("CLIENT_TOKEN", "MRPA_CLIENT_TOKEN"),
    )
    heartbeat: float = Field(
        default=5.0,
        validation_alias=AliasChoices("CLIENT_HEARTBEAT", "MRPA_CLIENT_HEARTBEAT"),
    )
    device_refresh: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "CLIENT_DEVICE_REFRESH", "MRPA_CLIENT_DEVICE_REFRESH"
        ),
    )
    reconnect_delay: float = Field(
        default=2.0,
        validation_alias=AliasChoices(
            "CLIENT_RECONNECT_DELAY", "MRPA_CLIENT_RECONNECT_DELAY"
        ),
    )
    command_poll_interval: float = Field(
        default=0.2,
        validation_alias=AliasChoices(
            "CLIENT_COMMAND_POLL", "MRPA_CLIENT_COMMAND_POLL"
        ),
    )
    ws_trace: bool = Field(
        default=False,
        validation_alias=AliasChoices("CLIENT_WS_TRACE", "MRPA_CLIENT_WS_TRACE"),
    )

    model_config = SettingsConfigDict(
        env_file=[str(path) for path in ENV_FILES],
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
