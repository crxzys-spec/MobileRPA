import base64
import json
from typing import List

from infra.http.client import post_json
from infra.http.errors import HttpError, HttpResponseError
from infra.llm.errors import LlmError, LlmResponseError
from infra.llm.types import LlmConfig


DEFAULT_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _post_openai(config: LlmConfig, payload: dict) -> str:
    if not config.api_key:
        raise LlmError("LLM API key is not set")
    url = config.base_url or DEFAULT_OPENAI_URL
    headers = {"Authorization": "Bearer {}".format(config.api_key)}
    try:
        return post_json(url, payload, headers=headers, timeout=config.timeout)
    except HttpResponseError as exc:
        raise LlmResponseError(exc.status, exc.body) from exc
    except HttpError as exc:
        raise LlmError("openai api error: {}".format(exc)) from exc


def _build_system_message():
    return {"role": "system", "content": "Return JSON only, no extra text."}


def call_text(config: LlmConfig, prompt: str) -> str:
    if not config.model:
        raise LlmError("LLM model is not set")
    payload = {
        "model": config.model,
        "messages": [
            _build_system_message(),
            {"role": "user", "content": prompt},
        ],
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_openai(config, payload)
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    return call_vision_multi(config, prompt, [png_bytes])


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
    if not config.model:
        raise LlmError("LLM model is not set")
    content = [{"type": "text", "text": prompt}]
    for image_bytes in images:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,{}".format(image_b64)},
            }
        )
    payload = {
        "model": config.model,
        "messages": [
            _build_system_message(),
            {"role": "user", "content": content},
        ],
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_openai(config, payload)
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]
