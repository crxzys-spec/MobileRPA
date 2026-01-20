import json
import urllib.error
import urllib.request

from infra.http.errors import HttpError, HttpResponseError


def post_json(url, payload, headers=None, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise HttpResponseError(err.code, detail) from err
    except urllib.error.URLError as err:
        raise HttpError(str(err)) from err


async def post_multipart(url, fields, files, headers=None, timeout=30):
    try:
        import aiohttp
    except ImportError as exc:
        raise HttpError("aiohttp is required for multipart HTTP requests") from exc
    data = aiohttp.FormData()
    for name, value in (fields or {}).items():
        data.add_field(name, str(value))
    for file_info in files or []:
        data.add_field(
            file_info["name"],
            file_info["content"],
            filename=file_info.get("filename"),
            content_type=file_info.get("content_type"),
        )
    request_headers = {}
    if headers:
        request_headers.update(headers)
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(url, data=data, headers=request_headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise HttpResponseError(resp.status, text.strip())
                return text
    except aiohttp.ClientError as exc:
        raise HttpError(str(exc)) from exc
