import base64
import json
from typing import List

from infra.http.client import post_json
from infra.http.errors import HttpError, HttpResponseError
from infra.llm.errors import LlmError, LlmResponseError
from infra.llm.types import LlmConfig


DEFAULT_AZURE_API_VERSION = "2024-06-01"


def _build_url(config: LlmConfig) -> str:
    if config.base_url:
        return config.base_url
    if not config.azure_endpoint:
        raise LlmError("AZURE_OPENAI_ENDPOINT is required for azure provider")
    if not config.azure_deployment:
        raise LlmError("AZURE_OPENAI_DEPLOYMENT is required for azure provider")
    api_version = config.azure_api_version or DEFAULT_AZURE_API_VERSION
    endpoint = config.azure_endpoint.rstrip("/")
    return "{}/openai/deployments/{}/chat/completions?api-version={}".format(
        endpoint,
        config.azure_deployment,
        api_version,
    )


def _post_azure(config: LlmConfig, payload: dict) -> str:
    if not config.api_key:
        raise LlmError("LLM API key is not set")
    url = _build_url(config)
    headers = {"api-key": config.api_key}
    try:
        return post_json(url, payload, headers=headers, timeout=config.timeout)
    except HttpResponseError as exc:
        raise LlmResponseError(exc.status, exc.body) from exc
    except HttpError as exc:
        raise LlmError("azure openai api error: {}".format(exc)) from exc


def _build_system_message():
    return {"role": "system", "content": "Return JSON only, no extra text."}


def call_text(config: LlmConfig, prompt: str) -> str:
    payload = {
        "messages": [
            _build_system_message(),
            {"role": "user", "content": prompt},
        ],
    }
    if config.model:
        payload["model"] = config.model
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_azure(config, payload)
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]


def call_vision(config: LlmConfig, prompt: str, png_bytes: bytes) -> str:
    return call_vision_multi(config, prompt, [png_bytes])


def call_vision_multi(config: LlmConfig, prompt: str, images: List[bytes]) -> str:
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
        "messages": [
            _build_system_message(),
            {"role": "user", "content": content},
        ],
    }
    if config.model:
        payload["model"] = config.model
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    body = _post_azure(config, payload)
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]
