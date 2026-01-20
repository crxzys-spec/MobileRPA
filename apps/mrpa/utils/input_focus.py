import re
from typing import Any, Dict, List, Optional


_ADB_KEYBOARD_ON_RE = re.compile(
    r"adb\s*keyboard\s*[\[{(]?\s*on\s*[\]})]?",
    re.IGNORECASE,
)


def _is_bottom(bounds: Any, height: Optional[int], ratio: float = 0.7) -> bool:
    if not bounds or not height:
        return False
    try:
        y1 = float(bounds[1])
        y2 = float(bounds[3])
    except (TypeError, ValueError, IndexError):
        return False
    return y1 >= height * ratio or y2 >= height * ratio


def _focus_from_items(items: List[Dict[str, Any]], screen_height: Optional[int], source: str) -> Optional[Dict[str, Any]]:
    for item in items or []:
        text = item.get("text")
        if not text:
            continue
        text_value = str(text).strip()
        if not text_value:
            continue
        if not _ADB_KEYBOARD_ON_RE.search(text_value):
            continue
        bounds = item.get("bounds")
        if bounds and screen_height:
            if not _is_bottom(bounds, screen_height):
                continue
        return {
            "focused": True,
            "evidence": text_value,
            "source": source,
        }
    return None


def detect_input_focus(
    elements: List[Dict[str, Any]],
    screen_height: Optional[int],
    *,
    ocr_payload: Optional[Dict[str, Any]] = None,
    ui_view: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = _focus_from_items(elements, screen_height, "elements")
    if result:
        return result
    if isinstance(ocr_payload, dict):
        ocr_elements = ocr_payload.get("elements")
        if isinstance(ocr_elements, list):
            result = _focus_from_items(ocr_elements, screen_height, "ocr")
            if result:
                return result
    if isinstance(ui_view, dict):
        ui_nodes = []
        for node in ui_view.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            text = node.get("text") or node.get("content_desc")
            if not text:
                continue
            ui_nodes.append({"text": text, "bounds": node.get("bounds")})
        result = _focus_from_items(ui_nodes, screen_height, "ui")
        if result:
            return result
    return {
        "focused": False,
        "evidence": None,
        "source": "none",
    }
