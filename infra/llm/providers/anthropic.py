import base64
import json
from typing import List

from infra.http.client import post_json
from infra.http.errors import HttpError, HttpResponseError
from infra.llm.errors import LlmError, LlmResponseError
from infra.llm.types import LlmConfig


DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


def _post_anthropic(config: LlmConfig, payload: dict) -> str:
    if not config.api_key:
        raise LlmError("LLM API key is not set")
    url = config.base_url or DEFAULT_ANTHROPIC_URL
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": config.anthropic_version or DEFAULT_ANTHROPIC_VERSION,
    }
    try:
        return post_json(url, payload, headers=headers, timeout=config.timeout)
    except HttpResponseError as exc:
        raise LlmResponseError(exc.status, exc.body) from exc
    except HttpError as exc:
        raise LlmError("anthropic api error: {}".format(exc)) from exc


def _build_message(prompt: str, images: List[bytes]) -> dict:
    content = [{"type": "text", "text": prompt}]
    for image_bytes in images:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            }
        )
    return {"role": "user", "content": content}


def _parse_response(body: str) -> str:
    data = json.loads(body)
    content = data.get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    if not parts:
        raise LlmError("anthropic response missing text content")
    return "".join(parts)


def call_text(config: LlmConfig, prompt: str) -> str:
    if not config.model:
        raise LlmError("LLM model is not set")
    payload = {
        "model": config.model,
        "max_tokens": int(config.max_tokens or 1024),
        "messages": [_build_message(prompt, [])],
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_anthropic(config, payload)
    return _parse_response(body)


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    return call_vision_multi(config, prompt, [png_bytes])


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
    if not config.model:
        raise LlmError("LLM model is not set")
    payload = {
        "model": config.model,
        "max_tokens": int(config.max_tokens or 1024),
        "messages": [_build_message(prompt, images)],
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_anthropic(config, payload)
    return _parse_response(body)
