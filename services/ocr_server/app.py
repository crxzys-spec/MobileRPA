import asyncio
import inspect
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic_settings import BaseSettings, SettingsConfigDict


app = FastAPI(title="MobileRPA OCR")

_OCR_CACHE: Dict[str, Any] = {}
_OCR_LOCK = threading.Lock()
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    device: str = "gpu"
    allow_cpu_fallback: bool = True
    api_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
    )


settings = Settings()


def _decode_image(png_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="invalid PNG image")
    return image


def _resolve_device(requested: Optional[str]) -> str:
    value = (requested or settings.device or "gpu").strip().lower()
    if value in ("gpu", "cuda"):
        return "gpu"
    if value in ("auto", ""):
        return "gpu"
    return "cpu"


def _build_paddleocr_kwargs(lang: str, device: str) -> Dict[str, Any]:
    from paddleocr import PaddleOCR

    sig = inspect.signature(PaddleOCR.__init__)
    params = sig.parameters
    accepts_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )

    def allow(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if accepts_kwargs:
            return kwargs
        return {key: value for key, value in kwargs.items() if key in params}

    kwargs: Dict[str, Any] = {"lang": lang}
    if device == "gpu":
        if "use_gpu" in params:
            kwargs["use_gpu"] = True
        elif "device" in params:
            kwargs["device"] = "gpu"
    else:
        if "use_gpu" in params:
            kwargs["use_gpu"] = False
        elif "device" in params:
            kwargs["device"] = "cpu"

    if "type" in params:
        kwargs["type"] = "ocr"
    elif "mode" in params:
        kwargs["mode"] = "ocr"

    if "use_textline_orientation" in params:
        kwargs["use_textline_orientation"] = False
    elif "use_angle_cls" in params:
        kwargs["use_angle_cls"] = False

    return allow(kwargs)


def _ensure_paddleocr(lang: str, device: str):
    from paddleocr import PaddleOCR

    cache_key = "{}:{}".format(lang, device)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]

    try:
        ocr = PaddleOCR(**_build_paddleocr_kwargs(lang, device))
    except Exception as exc:
        if device == "gpu" and settings.allow_cpu_fallback:
            return _ensure_paddleocr(lang, "cpu")
        raise HTTPException(status_code=500, detail=str(exc))

    _OCR_CACHE[cache_key] = ocr
    return ocr


def _normalize_result(result: Any) -> List[Any]:
    if result is None:
        return []
    if isinstance(result, dict):
        for key in ("ocr_result", "result", "data"):
            if key in result:
                result = result[key]
                break
    if not isinstance(result, list) and isinstance(result, Iterable):
        result = list(result)
    if (
        isinstance(result, list)
        and len(result) == 1
        and isinstance(result[0], list)
        and result[0]
    ):
        result = result[0]
    return result if isinstance(result, list) else []


def _extract_text(line: Any) -> Optional[Tuple[Any, str, float]]:
    if isinstance(line, dict):
        box = (
            line.get("box")
            or line.get("points")
            or line.get("poly")
            or line.get("polygon")
            or line.get("dt_polys")
        )
        text = line.get("text") or line.get("rec_text") or line.get("label")
        score = (
            line.get("score")
            or line.get("rec_score")
            or line.get("confidence")
            or 1.0
        )
        if box is None:
            return None
        return box, text, float(score)
    if isinstance(line, (list, tuple)) and len(line) >= 2:
        box = line[0]
        text_data = line[1]
        if isinstance(text_data, dict):
            text = text_data.get("text") or text_data.get("label")
            score = text_data.get("score") or text_data.get("confidence") or 1.0
        else:
            text = text_data[0] if isinstance(text_data, (list, tuple)) else None
            score = text_data[1] if isinstance(text_data, (list, tuple)) else 1.0
        return box, text, float(score)
    return None


def _bounds_from_box(box: Any) -> Optional[List[int]]:
    if not box:
        return None
    xs = [point[0] for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    ys = [point[1] for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not xs or not ys:
        return None
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _center(bounds: List[int]) -> Tuple[int, int]:
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def _parse_ocr_result(
    result: Any,
    score_threshold: float,
    offset: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    lines = _normalize_result(result)
    elements: List[Dict[str, Any]] = []
    used = set()
    for index, line in enumerate(lines, start=1):
        extracted = _extract_text(line)
        if not extracted:
            continue
        box, text, score = extracted
        if text is None:
            continue
        text = str(text).strip()
        if not text or float(score) < score_threshold:
            continue
        bounds = _bounds_from_box(box)
        if not bounds:
            continue
        if offset:
            dx, dy = offset
            bounds = [bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy]
        element_id = "ocr:{}".format(index)
        while element_id in used:
            index += 1
            element_id = "ocr:{}".format(index)
        used.add(element_id)
        cx, cy = _center(bounds)
        elements.append(
            {
                "id": element_id,
                "type": "text",
                "text": text,
                "bounds": bounds,
                "center": [cx, cy],
                "confidence": round(float(score), 3),
                "source": "ocr",
            }
        )
    return elements


def _run_ocr_sync(ocr: Any, image: np.ndarray) -> Any:
    with _OCR_LOCK:
        if hasattr(ocr, "predict"):
            return ocr.predict(image)
        return ocr.ocr(image)


def _check_api_key(x_api_key: Optional[str]) -> None:
    required = settings.api_key
    if not required:
        return
    if not x_api_key or x_api_key != required:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr")
async def ocr_endpoint(
    image: UploadFile = File(...),
    lang: str = Form("ch"),
    threshold: float = Form(0.5),
    device: Optional[str] = Form(None),
    offset_x: int = Form(0),
    offset_y: int = Form(0),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    _check_api_key(x_api_key)
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")
    screen = _decode_image(data)
    device = _resolve_device(device)
    ocr = _ensure_paddleocr(lang, device)
    result = await asyncio.to_thread(_run_ocr_sync, ocr, screen)
    elements = _parse_ocr_result(result, score_threshold=threshold, offset=(offset_x, offset_y))
    height, width = screen.shape[:2]
    return {
        "elements": elements,
        "meta": {"width": width, "height": height, "lang": lang, "device": device},
    }
