from typing import List

from infra.llm.errors import LlmError
from infra.llm.types import LlmConfig
from infra.llm.providers import anthropic, azure_openai, gemini, openai, openai_compat


_ALIASES = {
    "openai": "openai",
    "openai_compat": "openai_compat",
    "openai-compatible": "openai_compat",
    "openai-compat": "openai_compat",
    "compat": "openai_compat",
    "deepseek": "openai_compat",
    "qwen": "openai_compat",
    "azure": "azure_openai",
    "azure_openai": "azure_openai",
    "azure-openai": "azure_openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "gemini": "gemini",
    "google": "gemini",
}


def _resolve_provider(config: LlmConfig):
    name = (config.provider or "openai").strip().lower()
    if not name:
        name = "openai"
    provider = _ALIASES.get(name, name)
    if provider == "openai":
        return openai
    if provider == "openai_compat":
        return openai_compat
    if provider == "azure_openai":
        return azure_openai
    if provider == "anthropic":
        return anthropic
    if provider == "gemini":
        return gemini
    raise LlmError("unknown LLM provider: {}".format(config.provider))


def call_text(config: LlmConfig, prompt: str) -> str:
    provider = _resolve_provider(config)
    return provider.call_text(config, prompt)


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    provider = _resolve_provider(config)
    return provider.call_vision(config, prompt, png_bytes)


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
    provider = _resolve_provider(config)
    return provider.call_vision_multi(config, prompt, images)
