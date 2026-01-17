import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


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


class ClientSettings(BaseSettings):
    adb_path: str = Field(
        default="adb",
        validation_alias=AliasChoices("ADB_PATH", "MRPA_ADB_PATH"),
    )
    device_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DEVICE_ID", "MRPA_DEVICE_ID"),
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "MRPA_OPENAI_API_KEY"),
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "MRPA_OPENAI_MODEL"),
    )
    ocr: OCRSettings = OCRSettings()

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return env_settings, dotenv_settings, init_settings, file_secret_settings


def load_settings(config_path: Optional[str]) -> ClientSettings:
    data = {}
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError("config not found: {}".format(path))
        data = _load_json(path)
    else:
        candidates = [
            Path("config") / "config.json",
            Path("config.json"),
        ]
        for candidate in candidates:
            if candidate.exists():
                data = _load_json(candidate)
                break
    data = _apply_ocr_env_overrides(data or {})
    return ClientSettings(**data)


def _apply_ocr_env_overrides(data):
    ocr = dict(data.get("ocr") or {})
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
        value = os.getenv(env_key)
        if value in (None, ""):
            continue
        if field == "timeout":
            try:
                value = float(value)
            except ValueError:
                continue
        ocr[field] = value
    if ocr:
        data = dict(data)
        data["ocr"] = ocr
    return data


def _load_json(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))
