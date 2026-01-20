import json
from typing import Any, Dict, List

from shared.utils.geometry import bounds_center


def _unique_id(base: str, used: set) -> str:
    if base not in used:
        used.add(base)
        return base
    index = 2
    while True:
        candidate = "{}:{}".format(base, index)
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _result_to_dict(item):
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


def _coerce_list(value):
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


def _get_value(mapping: Dict[str, Any], keys, default):
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None:
                return value
    return default


def _bounds_from_box(box):
    if box is None:
        return None
    if hasattr(box, "tolist"):
        try:
            box = box.tolist()
        except Exception:
            pass
    xs = []
    ys = []
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


def parse_ocr_result(result, score_threshold: float = 0.5) -> List[Dict[str, Any]]:
    lines = result
    container_keys = ("ocr_result", "result", "data", "res")
    if isinstance(lines, list):
        converted = []
        converted_any = False
        for item in lines:
            data = _result_to_dict(item)
            if data is not None:
                converted.append(data)
                converted_any = True
            else:
                converted.append(item)
        if converted_any:
            lines = converted
        if lines and all(isinstance(item, dict) for item in lines):
            flattened = []
            for item in lines:
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
            lines = flattened
    if isinstance(lines, dict):
        nested = None
        for key in container_keys:
            if key in lines:
                nested = lines.get(key)
                break
        if nested is None:
            lines = [lines]
        elif isinstance(nested, list):
            lines = nested
        else:
            lines = [nested]
    if not isinstance(lines, list) and hasattr(lines, "__iter__"):
        lines = list(lines)
    if (
        lines
        and isinstance(lines, list)
        and len(lines) == 1
        and isinstance(lines[0], list)
        and lines[0]
    ):
        lines = lines[0]
    elements: List[Dict[str, Any]] = []
    used_ids = set()
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
                index += 1
                element_id = _unique_id("ocr:{}".format(index), used_ids)
                center_x, center_y = bounds_center(bounds)
                elements.append(
                    {
                        "id": element_id,
                        "type": "text",
                        "text": text,
                        "bounds": bounds,
                        "center": [center_x, center_y],
                        "confidence": round(float(score), 3),
                        "source": "ocr",
                    }
                )
            continue
        if line is None:
            continue
        if isinstance(line, (list, tuple, dict)) and not line:
            continue
        box = None
        text = None
        score = None
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
        elif isinstance(line, (list, tuple)) and len(line) >= 2:
            box = line[0]
            text_data = line[1]
            if isinstance(text_data, dict):
                text = text_data.get("text") or text_data.get("label")
                score = text_data.get("score") or text_data.get("confidence") or 1.0
            else:
                text = text_data[0] if isinstance(text_data, (list, tuple)) else None
                score = text_data[1] if isinstance(text_data, (list, tuple)) else 1.0
        if text is None:
            continue
        text = str(text).strip()
        if not text or float(score) < score_threshold:
            continue
        if box is None:
            continue
        bounds = _bounds_from_box(box)
        if not bounds:
            continue
        index += 1
        element_id = _unique_id("ocr:{}".format(index), used_ids)
        center_x, center_y = bounds_center(bounds)
        elements.append(
            {
                "id": element_id,
                "type": "text",
                "text": text,
                "bounds": bounds,
                "center": [center_x, center_y],
                "confidence": round(float(score), 3),
                "source": "ocr",
            }
        )
    return elements
