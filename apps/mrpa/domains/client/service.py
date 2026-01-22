import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from fastapi import HTTPException


def _normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _raise_unavailable(error: Exception) -> None:
    raise HTTPException(
        status_code=502,
        detail="client unavailable: {}".format(error),
    ) from error


@dataclass
class ClientApi:
    base_url: str
    timeout: float = 10.0

    def __post_init__(self) -> None:
        self.base_url = _normalize_base(self.base_url)

    def _url(self, path: str) -> str:
        return "{}{}".format(self.base_url, path)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        url = self._url(path)
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise HTTPException(
                status_code=err.code, detail=detail or err.reason
            ) from err
        except urllib.error.URLError as err:
            _raise_unavailable(err)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=502, detail="invalid JSON from client"
            ) from err

    def _stream(self, path: str) -> Tuple[str, Iterable[bytes]]:
        url = self._url(path)
        try:
            response = urllib.request.urlopen(url, timeout=self.timeout)
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise HTTPException(
                status_code=err.code, detail=detail or err.reason
            ) from err
        except urllib.error.URLError as err:
            _raise_unavailable(err)

        content_type = response.headers.get(
            "Content-Type",
            "multipart/x-mixed-replace; boundary=frame",
        )

        def iterator() -> Iterable[bytes]:
            try:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    response.close()
                except Exception:
                    pass

        return content_type, iterator()

    def list_devices(self) -> list[Dict[str, Any]]:
        return self._request("GET", "/api/devices") or []

    def list_device_sessions(self) -> list[Dict[str, Any]]:
        return self._request("GET", "/api/device/sessions") or []

    def get_device_session(self, device_id: str) -> Dict[str, Any]:
        return self._request(
            "GET", "/api/device/{}/session".format(device_id)
        )

    def list_device_commands(
        self, device_id: str, limit: int = 50
    ) -> list[Dict[str, Any]]:
        return (
            self._request(
                "GET",
                "/api/device/{}/commands?limit={}".format(device_id, limit),
            )
            or []
        )

    def enqueue_device_command(
        self, device_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/device/{}/commands".format(device_id),
            payload=payload,
        )

    def clear_device_queue(self, device_id: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/device/{}/queue/clear".format(device_id),
            payload={},
        )

    def close_device_session(self, device_id: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/device/{}/session/close".format(device_id),
            payload={},
        )

    def webrtc_config(self) -> Dict[str, Any]:
        return self._request("GET", "/api/webrtc/config") or {}

    async def webrtc_offer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._request,
            "POST",
            "/api/webrtc/offer",
            payload,
        )

    def stream_mjpeg(self, device_id: str) -> Tuple[str, Iterable[bytes]]:
        return self._stream("/api/stream/{}.mjpg".format(device_id))

    def list_stream_sessions(self) -> list[Dict[str, Any]]:
        return self._request("GET", "/api/stream/sessions") or []

    def get_stream_session(self, device_id: str) -> Dict[str, Any]:
        return self._request(
            "GET", "/api/stream/{}/session".format(device_id)
        )

    def start_stream_session(
        self, device_id: str, payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/stream/{}/start".format(device_id),
            payload=payload or {},
        )

    def restart_stream_session(
        self, device_id: str, payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/stream/{}/restart".format(device_id),
            payload=payload or {},
        )

    def stop_stream_session(self, device_id: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/stream/{}/stop".format(device_id),
            payload={},
        )

    def update_stream_session_config(
        self, device_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/stream/{}/config".format(device_id),
            payload=payload,
        )
