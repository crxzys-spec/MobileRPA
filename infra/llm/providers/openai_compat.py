from typing import List

from infra.llm.errors import LlmError
from infra.llm.types import LlmConfig
from infra.llm.providers import openai


def _ensure_base_url(config: LlmConfig) -> None:
    if not config.base_url:
        raise LlmError("LLM_BASE_URL is required for openai_compat providers")


def call_text(config: LlmConfig, prompt: str) -> str:
    _ensure_base_url(config)
    return openai.call_text(config, prompt)


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    _ensure_base_url(config)
    return openai.call_vision(config, prompt, png_bytes)


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
    _ensure_base_url(config)
    return openai.call_vision_multi(config, prompt, images)
