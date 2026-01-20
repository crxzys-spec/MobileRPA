import base64
import json
from typing import List

from infra.http.client import post_json
from infra.http.errors import HttpError, HttpResponseError
from infra.llm.errors import LlmError, LlmResponseError
from infra.llm.types import LlmConfig


DEFAULT_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
)


def _build_url(config: LlmConfig) -> str:
    if config.base_url:
        return config.base_url
    if not config.api_key:
        raise LlmError("LLM API key is not set")
    if not config.model:
        raise LlmError("LLM model is not set")
    return DEFAULT_GEMINI_URL.format(model=config.model, api_key=config.api_key)


def _post_gemini(config: LlmConfig, payload: dict) -> str:
    url = _build_url(config)
    try:
        return post_json(url, payload, headers=None, timeout=config.timeout)
    except HttpResponseError as exc:
        raise LlmResponseError(exc.status, exc.body) from exc
    except HttpError as exc:
        raise LlmError("gemini api error: {}".format(exc)) from exc


def _build_parts(prompt: str, images: List[bytes]) -> List[dict]:
    parts = [{"text": prompt}]
    for image_bytes in images:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": image_b64,
                }
            }
        )
    return parts


def _parse_response(body: str) -> str:
    data = json.loads(body)
    candidates = data.get("candidates") or []
    if not candidates:
        raise LlmError("gemini response missing candidates")
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            texts.append(part.get("text", ""))
    if not texts:
        raise LlmError("gemini response missing text content")
    return "".join(texts)


def call_text(config: LlmConfig, prompt: str) -> str:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": _build_parts(prompt, []),
            }
        ]
    }
    if config.temperature is not None:
        payload["generationConfig"] = {"temperature": config.temperature}
    body = _post_gemini(config, payload)
    return _parse_response(body)


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    return call_vision_multi(config, prompt, [png_bytes])


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": _build_parts(prompt, images),
            }
        ]
    }
    if config.temperature is not None:
        payload["generationConfig"] = {"temperature": config.temperature}
    body = _post_gemini(config, payload)
    return _parse_response(body)
