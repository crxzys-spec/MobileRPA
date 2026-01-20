import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple


_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_SEARCH_TOKEN = "\u641c\u7d22"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bounds(bounds: Any) -> Optional[Tuple[float, float, float, float]]:
    if not bounds or not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    try:
        left, top, right, bottom = [float(item) for item in bounds]
    except (TypeError, ValueError):
        return None
    return left, top, right, bottom


def _center_y(bounds: Any) -> Optional[float]:
    parsed = _parse_bounds(bounds)
    if parsed is None:
        return None
    _, top, _, bottom = parsed
    return (top + bottom) / 2.0


def _region_for(bounds: Any, height: Optional[int]) -> str:
    if not height:
        return "middle"
    center_y = _center_y(bounds)
    if center_y is None:
        return "middle"
    if center_y <= height * 0.25:
        return "top"
    if center_y >= height * 0.75:
        return "bottom"
    return "middle"


def _collect_items(
    elements: List[Dict[str, Any]],
    ocr_payload: Optional[Dict[str, Any]],
    ui_view: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for element in elements or []:
        text = _normalize_text(element.get("text"))
        if not text:
            continue
        items.append({"text": text, "bounds": element.get("bounds"), "source": "elements"})
    if isinstance(ocr_payload, dict):
        ocr_elements = ocr_payload.get("elements")
        if isinstance(ocr_elements, list):
            for element in ocr_elements:
                if not isinstance(element, dict):
                    continue
                text = _normalize_text(element.get("text"))
                if not text:
                    continue
                items.append({"text": text, "bounds": element.get("bounds"), "source": "ocr"})
    if isinstance(ui_view, dict):
        for node in ui_view.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            text = _normalize_text(node.get("text") or node.get("content_desc") or node.get("resource_id"))
            if not text:
                continue
            items.append({"text": text, "bounds": node.get("bounds"), "source": "ui"})
    return items


def _dedupe_texts(items: List[Dict[str, Any]], height: Optional[int], region: str, limit: int) -> List[str]:
    seen = set()
    ordered: List[Tuple[float, float, str]] = []
    for item in items:
        if _region_for(item.get("bounds"), height) != region:
            continue
        text = _normalize_text(item.get("text"))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        bounds = _parse_bounds(item.get("bounds")) or (0.0, 0.0, 0.0, 0.0)
        ordered.append((bounds[1], bounds[0], text))
    ordered.sort()
    return [text for _, _, text in ordered[:limit]]


def _normalize_token(text: str) -> str:
    token = text.strip().lower()
    if not token:
        return ""
    if token.isdigit():
        return ""
    if len(token) < 2 and not _CHINESE_RE.search(token):
        return ""
    return token


def _signature(tokens: List[str]) -> str:
    payload = "|".join(tokens)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_page_hint(
    elements: List[Dict[str, Any]],
    screen_height: Optional[int],
    *,
    ocr_payload: Optional[Dict[str, Any]] = None,
    ui_view: Optional[Dict[str, Any]] = None,
    max_items: int = 6,
    max_tokens: int = 40,
) -> Dict[str, Any]:
    items = _collect_items(elements, ocr_payload, ui_view)
    top_texts = _dedupe_texts(items, screen_height, "top", max_items)
    bottom_nav = _dedupe_texts(items, screen_height, "bottom", max_items)
    tokens: List[str] = []
    seen = set()
    for item in items:
        token = _normalize_token(_normalize_text(item.get("text")))
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    tokens.sort()
    has_search = any(
        _SEARCH_TOKEN in _normalize_text(item.get("text"))
        or "search" in _normalize_text(item.get("text")).lower()
        for item in items
    )
    return {
        "top_texts": top_texts,
        "bottom_nav": bottom_nav,
        "has_search": has_search,
        "signature": _signature(tokens),
    }
