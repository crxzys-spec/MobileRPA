from typing import Any, Dict, List, Optional, Tuple

from shared.utils.geometry import bounds_center


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


def _bounds_valid(bounds: Any) -> bool:
    parsed = _parse_bounds(bounds)
    if parsed is None:
        return False
    left, top, right, bottom = parsed
    if left == right == top == bottom == 0:
        return False
    return right > left and bottom > top


def _node_label(node: Dict[str, Any]) -> str:
    return (
        _normalize_text(node.get("text"))
        or _normalize_text(node.get("content_desc"))
        or _normalize_text(node.get("resource_id"))
    )


def _is_valid_node(node: Dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    label = _node_label(node)
    if not label:
        return False
    return _bounds_valid(node.get("bounds"))


def ui_view_has_valid_nodes(ui_view: Any) -> bool:
    if not isinstance(ui_view, dict):
        return False
    nodes = ui_view.get("nodes") or []
    for node in nodes:
        if _is_valid_node(node):
            return True
    return False


def ui_nodes_to_elements(ui_view: Any) -> List[Dict[str, Any]]:
    if not isinstance(ui_view, dict):
        return []
    nodes = ui_view.get("nodes") or []
    elements: List[Dict[str, Any]] = []
    for node in nodes:
        if not _is_valid_node(node):
            continue
        bounds = node.get("bounds")
        try:
            center = bounds_center(bounds)
        except Exception:
            center = None
        label = _node_label(node)
        elements.append(
            {
                "id": "ui_{}".format(len(elements)),
                "type": "ui_node",
                "text": label,
                "bounds": bounds,
                "center": center,
                "confidence": None,
                "source": "ui",
                "resource_id": node.get("resource_id"),
                "class": node.get("class"),
            }
        )
    return elements
