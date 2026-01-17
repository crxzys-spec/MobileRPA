import asyncio
import inspect
import json
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
        extra="ignore",
    )


settings = Settings()


def _patch_paddle_analysis_config() -> None:
    try:
        import paddle
    except Exception:
        return
    try:
        lib = getattr(paddle, "base", None)
        lib = getattr(lib, "libpaddle", None)
        config_cls = getattr(lib, "AnalysisConfig", None)
        if not config_cls or hasattr(config_cls, "set_optimization_level"):
            return

        def _set_optimization_level(self, level):  # type: ignore[no-redef]
            try:
                if hasattr(self, "set_tensorrt_optimization_level"):
                    self.set_tensorrt_optimization_level(level)
                elif hasattr(self, "tensorrt_optimization_level"):
                    self.tensorrt_optimization_level = level
            except Exception:
                pass

        setattr(config_cls, "set_optimization_level", _set_optimization_level)
    except Exception:
        return


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


def _build_structure_kwargs(lang: str, device: str) -> Dict[str, Any]:
    from paddleocr import PPStructureV3

    sig = inspect.signature(PPStructureV3.__init__)
    params = sig.parameters
    accepts_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )

    def allow(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if accepts_kwargs:
            return kwargs
        return {key: value for key, value in kwargs.items() if key in params}

    kwargs: Dict[str, Any] = {}
    if "lang" in params:
        kwargs["lang"] = lang
    elif "ocr_lang" in params:
        kwargs["ocr_lang"] = lang
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

    if "use_doc_orientation_classify" in params:
        kwargs["use_doc_orientation_classify"] = False
    if "use_doc_unwarping" in params:
        kwargs["use_doc_unwarping"] = False
    if "use_textline_orientation" in params:
        kwargs["use_textline_orientation"] = False

    return allow(kwargs)


def _ensure_structure(lang: str, device: str):
    from paddleocr import PPStructureV3

    cache_key = "structure:{}:{}".format(lang, device)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]

    _patch_paddle_analysis_config()
    try:
        ocr = PPStructureV3(**_build_structure_kwargs(lang, device))
    except Exception as exc:
        if device == "gpu" and settings.allow_cpu_fallback:
            return _ensure_structure(lang, "cpu")
        raise HTTPException(status_code=500, detail=str(exc))

    _OCR_CACHE[cache_key] = ocr
    return ocr


def _result_to_dict(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, dict):
        return item
    res = getattr(item, "res", None)
    if isinstance(res, dict):
        return {"res": res}
    for attr in ("to_dict", "dict", "as_dict"):
        func = getattr(item, attr, None)
        if callable(func):
            try:
                data = func()
            except Exception:
                continue
            if isinstance(data, dict):
                return data
    for attr in ("json", "to_json"):
        func = getattr(item, attr, None)
        if callable(func):
            try:
                raw = func()
            except Exception:
                continue
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data
    data = getattr(item, "__dict__", None)
    if isinstance(data, dict) and data:
        return data
    return None


def _normalize_result(result: Any) -> List[Any]:
    if result is None:
        return []
    container_keys = ("ocr_result", "result", "data", "res", "overall_ocr_res")
    if isinstance(result, list):
        converted = []
        converted_any = False
        for item in result:
            data = _result_to_dict(item)
            if data is not None:
                converted.append(data)
                converted_any = True
            else:
                converted.append(item)
        if converted_any:
            result = converted
        if result and all(isinstance(item, dict) for item in result):
            flattened = []
            for item in result:
                nested = None
                for key in container_keys:
                    if key in item:
                        nested = item.get(key)
                        break
                if nested is None:
                    flattened.append(item)
                elif isinstance(nested, list):
                    flattened.extend(nested)
                else:
                    flattened.append(nested)
            result = flattened
    if isinstance(result, dict):
        nested = None
        for key in container_keys:
            if key in result:
                nested = result.get(key)
                break
        if nested is None:
            return [result]
        if isinstance(nested, list):
            result = nested
        else:
            return [nested]
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


def _coerce_list(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:
            return value
    if isinstance(value, list):
        return [_coerce_list(item) for item in value]
    return value


_RAW_DROP_KEYS = {"input_img", "rot_img", "output_img", "vis_fonts"}
class _RawDrop:
    pass


_RAW_DROP = _RawDrop()


def _sanitize_raw(value: Any, key: Optional[str] = None) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if key and key.lower() in _RAW_DROP_KEYS:
        return _RAW_DROP
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _RAW_DROP
    if isinstance(value, np.ndarray):
        if key and key.lower() in _RAW_DROP_KEYS:
            return _RAW_DROP
        return value.tolist()
    if hasattr(value, "tolist"):
        try:
            converted = value.tolist()
        except Exception:
            converted = None
        if converted is not None:
            return _sanitize_raw(converted, key=key)
    if isinstance(value, dict):
        cleaned = {}
        for item_key, item_value in value.items():
            cleaned_value = _sanitize_raw(item_value, key=str(item_key))
            if cleaned_value is _RAW_DROP:
                continue
            cleaned[str(item_key)] = cleaned_value
        return cleaned
    if isinstance(value, (list, tuple, set, frozenset)):
        cleaned_list = []
        for item in value:
            cleaned_item = _sanitize_raw(item)
            if cleaned_item is _RAW_DROP:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list
    return str(value)


def _serialize_raw_result(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, list):
        serialized = []
        for item in result:
            data = _result_to_dict(item)
            serialized_item = _sanitize_raw(data if data is not None else item)
            if serialized_item is _RAW_DROP:
                continue
            serialized.append(serialized_item)
        return serialized
    data = _result_to_dict(result)
    if data is not None:
        serialized = _sanitize_raw(data)
        return None if serialized is _RAW_DROP else serialized
    if not isinstance(result, list) and isinstance(result, Iterable):
        serialized = _sanitize_raw(list(result))
        return None if serialized is _RAW_DROP else serialized
    serialized = _sanitize_raw(result)
    return None if serialized is _RAW_DROP else serialized


def _summarize_boxes(boxes: Any) -> List[Dict[str, Any]]:
    if not isinstance(boxes, list):
        return []
    summary = []
    for item in boxes:
        if not isinstance(item, dict):
            continue
        bounds = _bounds_from_box(
            item.get("coordinate")
            or item.get("bbox")
            or item.get("box")
            or item.get("bounds")
        )
        summary.append(
            {
                "label": item.get("label"),
                "score": item.get("score"),
                "bounds": bounds,
                "raw_box": item.get("coordinate") or item.get("bbox") or item.get("box"),
            }
        )
    return summary


def _summarize_ocr(ocr: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(ocr, dict):
        return {}
    texts = _coerce_list(ocr.get("rec_texts") or []) or []
    scores = _coerce_list(ocr.get("rec_scores") or []) or []
    boxes = _coerce_list(ocr.get("rec_boxes") or []) or []
    polys = _coerce_list(ocr.get("rec_polys") or []) or []
    lines = []
    for i, text in enumerate(texts):
        if text is None:
            continue
        score = scores[i] if i < len(scores) else None
        bounds = None
        if i < len(boxes):
            bounds = _bounds_from_box(boxes[i])
        if bounds is None and i < len(polys):
            bounds = _bounds_from_box(polys[i])
        lines.append(
            {
                "text": str(text),
                "score": score,
                "bounds": bounds,
                "poly": polys[i] if i < len(polys) else None,
            }
        )
    return {
        "lines": lines,
        "count": len(lines),
        "text_det_params": ocr.get("text_det_params"),
        "text_type": ocr.get("text_type"),
        "model_settings": ocr.get("model_settings"),
    }


def _summarize_structure(raw_result: Any) -> Dict[str, Any]:
    if isinstance(raw_result, list) and raw_result:
        page = raw_result[0] if isinstance(raw_result[0], dict) else {}
    elif isinstance(raw_result, dict):
        page = raw_result
    else:
        return {}
    layout = _summarize_boxes(
        (page.get("layout_det_res") or {}).get("boxes")
    )
    regions = _summarize_boxes(
        (page.get("region_det_res") or {}).get("boxes")
    )
    images = []
    imgs = page.get("imgs_in_doc")
    if isinstance(imgs, list):
        for item in imgs:
            if not isinstance(item, dict):
                continue
            images.append(
                {
                    "path": item.get("path"),
                    "score": item.get("score"),
                    "bounds": _bounds_from_box(item.get("coordinate")),
                    "raw_box": item.get("coordinate"),
                }
            )
    ocr_summary = _summarize_ocr(page.get("overall_ocr_res") or {})
    return {
        "page": {
            "width": page.get("width"),
            "height": page.get("height"),
            "angle": (page.get("doc_preprocessor_res") or {}).get("angle"),
        },
        "layout_boxes": layout,
        "region_boxes": regions,
        "images": images,
        "ocr": ocr_summary,
        "parsing": page.get("parsing_res_list") or [],
        "model_settings": page.get("model_settings"),
    }


def _extract_text(line: Any) -> Optional[Tuple[Any, str, float]]:
    if isinstance(line, dict):
        box = (
            line.get("box")
            or line.get("bbox")
            or line.get("bounds")
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


def _flatten_structure_result(result: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()

    def add_item(text: Any, box: Any, score: Any) -> None:
        if text is None:
            return
        text_value = str(text).strip()
        if not text_value:
            return
        box_key = None
        if box is not None:
            try:
                coerced = _coerce_list(box)
                if isinstance(coerced, dict):
                    box_key = tuple(sorted(coerced.items()))
                elif isinstance(coerced, list):
                    box_key = tuple(
                        tuple(point) if isinstance(point, list) else point
                        for point in coerced
                    )
                else:
                    box_key = coerced
            except Exception:
                box_key = None
        key = (text_value, box_key)
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "text": text_value,
                "box": box,
                "score": 1.0 if score is None else score,
            }
        )

    def visit(obj: Any, parent_box: Any = None) -> None:
        if isinstance(obj, dict):
            box = (
                obj.get("bbox")
                or obj.get("box")
                or obj.get("bounds")
                or obj.get("polygon")
                or obj.get("poly")
                or obj.get("points")
            )
            text = obj.get("text") or obj.get("rec_text") or obj.get("label")
            score = obj.get("score") or obj.get("confidence") or obj.get("rec_score")
            if text is not None and (box is not None or parent_box is not None):
                add_item(text, box or parent_box, score)
            res = obj.get("res")
            if isinstance(res, list):
                for item in res:
                    if isinstance(item, dict):
                        item_box = (
                            item.get("bbox")
                            or item.get("box")
                            or item.get("bounds")
                            or item.get("polygon")
                            or item.get("poly")
                            or item.get("points")
                        )
                        item_text = (
                            item.get("text")
                            or item.get("rec_text")
                            or item.get("label")
                        )
                        item_score = (
                            item.get("score")
                            or item.get("confidence")
                            or item.get("rec_score")
                            or score
                        )
                        if item_text is not None:
                            add_item(item_text, item_box or box or parent_box, item_score)
                        else:
                            visit(item, parent_box=box or parent_box)
                    else:
                        visit(item, parent_box=box or parent_box)
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    visit(value, parent_box=box or parent_box)
        elif isinstance(obj, list):
            for item in obj:
                visit(item, parent_box=parent_box)

    visit(result)
    return items


def _bounds_from_box(box: Any) -> Optional[List[int]]:
    if box is None:
        return None
    if hasattr(box, "tolist"):
        try:
            box = box.tolist()
        except Exception:
            pass
    if isinstance(box, dict) and all(key in box for key in ("x1", "y1", "x2", "y2")):
        try:
            return [
                int(box["x1"]),
                int(box["y1"]),
                int(box["x2"]),
                int(box["y2"]),
            ]
        except Exception:
            return None
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            return [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
        except Exception:
            pass
    xs: List[float] = []
    ys: List[float] = []
    for point in box:
        if hasattr(point, "tolist"):
            try:
                point = point.tolist()
            except Exception:
                pass
        try:
            x = point[0]
            y = point[1]
        except Exception:
            continue
        xs.append(x)
        ys.append(y)
    if not xs or not ys:
        return None
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _center(bounds: List[int]) -> Tuple[int, int]:
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def _get_value(mapping: Dict[str, Any], keys: Iterable[str], default: Any) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None:
                return value
    return default


def _parse_ocr_result(
    result: Any,
    score_threshold: float,
    offset: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    lines = _flatten_structure_result(result)
    if not lines:
        lines = _normalize_result(result)
    elements: List[Dict[str, Any]] = []
    used = set()
    index = 0
    for line in lines or []:
        if isinstance(line, dict) and (
            "rec_texts" in line or "rec_polys" in line or "rec_boxes" in line
        ):
            texts = _coerce_list(_get_value(line, ("rec_texts",), [])) or []
            scores = _coerce_list(_get_value(line, ("rec_scores",), [])) or []
            polys = _coerce_list(_get_value(line, ("rec_polys", "dt_polys"), [])) or []
            boxes = _coerce_list(_get_value(line, ("rec_boxes",), [])) or []
            for i, text in enumerate(texts):
                score = scores[i] if i < len(scores) else 1.0
                if text is None:
                    continue
                text = str(text).strip()
                if not text or float(score) < score_threshold:
                    continue
                bounds = None
                if polys and i < len(polys):
                    bounds = _bounds_from_box(polys[i])
                elif boxes and i < len(boxes):
                    box = boxes[i]
                    try:
                        bounds = [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
                    except Exception:
                        bounds = None
                if not bounds:
                    continue
                if offset:
                    dx, dy = offset
                    bounds = [
                        bounds[0] + dx,
                        bounds[1] + dy,
                        bounds[2] + dx,
                        bounds[3] + dy,
                    ]
                index += 1
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
            continue
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
        index += 1
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
            try:
                sig = inspect.signature(ocr.predict)
            except (TypeError, ValueError):
                return ocr.predict(image)
            if "input" in sig.parameters:
                return ocr.predict(input=image)
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
    raw: bool = Form(False),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    _check_api_key(x_api_key)
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")
    screen = _decode_image(data)
    device = _resolve_device(device)
    ocr = _ensure_structure(lang, device)
    result = await asyncio.to_thread(_run_ocr_sync, ocr, screen)
    elements = _parse_ocr_result(result, score_threshold=threshold, offset=(offset_x, offset_y))
    height, width = screen.shape[:2]
    payload = {
        "elements": elements,
        "meta": {"width": width, "height": height, "lang": lang, "device": device},
    }
    if raw:
        raw_result = _serialize_raw_result(result)
        payload["raw_result"] = raw_result
        payload["structure"] = _summarize_structure(raw_result)
    return payload
