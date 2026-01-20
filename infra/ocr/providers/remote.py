import asyncio
import json

from infra.http.client import post_multipart
from infra.http.errors import HttpError, HttpResponseError
from infra.ocr.types import OcrRequest, OcrResult
from shared.errors import AdbError
from infra.image.image import encode_png


async def remote_ocr_request(
    url,
    png_bytes,
    lang="ch",
    score_threshold=0.5,
    timeout=30,
    api_key=None,
    device=None,
    raw=False,
    annotate=False,
):
    try:
        fields = {"lang": lang, "threshold": score_threshold}
        if device:
            fields["device"] = device
        if raw:
            fields["raw"] = "1"
        if annotate:
            fields["annotate"] = "1"
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key
        text = await post_multipart(
            url,
            fields=fields,
            files=[
                {
                    "name": "image",
                    "content": png_bytes,
                    "filename": "screen.png",
                    "content_type": "image/png",
                }
            ],
            headers=headers,
            timeout=timeout,
        )
    except HttpResponseError as exc:
        raise AdbError("remote OCR failed: {} {}".format(exc.status, exc.body)) from exc
    except HttpError as exc:
        raise AdbError("remote OCR request failed: {}".format(exc)) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdbError("remote OCR returned invalid JSON") from exc


def run(request: OcrRequest) -> OcrResult:
    if not request.remote_url:
        raise AdbError("remote OCR endpoint is not configured")
    png_bytes = encode_png(request.image)
    payload = asyncio.run(
        remote_ocr_request(
            request.remote_url,
            png_bytes,
            lang=request.lang,
            score_threshold=request.threshold,
            timeout=request.remote_timeout,
            api_key=request.remote_api_key,
            device=request.remote_device,
            raw=request.raw,
            annotate=request.annotate,
        )
    )
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise AdbError("remote OCR returned unexpected payload")
    return OcrResult(elements=elements, payload=payload)
