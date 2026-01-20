import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.errors import AdbError
from shared.utils.geometry import bounds_center


@dataclass
class SkillDefinition:
    name: str
    description: str
    handler: str
    params: Dict[str, Any]

    def to_prompt(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "description": self.description,
            "params": self.params,
        }
        return payload


@dataclass
class SkillResult:
    actions: List[Dict[str, Any]]
    error: Optional[str] = None


class SkillExecutionError(AdbError):
    pass


class SkillLibrary:
    def __init__(self, skills: List[SkillDefinition], source_dir: Optional[Path] = None):
        self.skills = skills
        self.source_dir = source_dir
        self._index = {skill.name: skill for skill in skills}

    @classmethod
    def load_from_dir(cls, path: Optional[str]) -> "SkillLibrary":
        if not path:
            return cls([])
        directory = Path(path)
        if not directory.exists() or not directory.is_dir():
            return cls([], source_dir=directory)
        skills: List[SkillDefinition] = []
        for item in sorted(directory.glob("*.json")):
            try:
                data = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            name = str(data.get("name") or "").strip()
            description = str(data.get("description") or "").strip()
            handler = str(data.get("handler") or "").strip()
            params = data.get("params") or {}
            if not name or not description or not handler:
                continue
            if not isinstance(params, dict):
                params = {}
            skills.append(
                SkillDefinition(
                    name=name,
                    description=description,
                    handler=handler,
                    params=params,
                )
            )
        return cls(skills, source_dir=directory)

    def list_for_prompt(self) -> List[Dict[str, Any]]:
        return [skill.to_prompt() for skill in self.skills]

    def get(self, name: Optional[str]) -> Optional[SkillDefinition]:
        if not name:
            return None
        return self._index.get(name)


def _match_text(candidate: str, target: str, mode: str) -> bool:
    if mode == "exact":
        return candidate == target
    return target in candidate


def _normalize_match_mode(value: Optional[str]) -> str:
    mode = (value or "contains").strip().lower()
    if mode not in ("contains", "exact"):
        return "contains"
    return mode


def _normalize_source(value: Optional[str]) -> str:
    source = (value or "elements").strip().lower()
    if source not in ("elements", "ui", "both"):
        return "elements"
    return source


def _find_element_match(elements, text: str, mode: str) -> Optional[Dict[str, Any]]:
    best = None
    best_score = -1.0
    for element in elements or []:
        candidate = element.get("text")
        if not candidate:
            continue
        candidate_text = str(candidate).strip()
        if not candidate_text:
            continue
        if not _match_text(candidate_text, text, mode):
            continue
        score = element.get("confidence")
        try:
            score_val = float(score) if score is not None else 0.0
        except (TypeError, ValueError):
            score_val = 0.0
        if score_val >= best_score:
            best_score = score_val
            best = element
    return best


def _find_ui_match(ui_view, text: str, mode: str) -> Optional[Dict[str, Any]]:
    if not isinstance(ui_view, dict):
        return None
    for node in ui_view.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        candidates = [node.get("text"), node.get("content_desc")]
        for candidate in candidates:
            if not candidate:
                continue
            candidate_text = str(candidate).strip()
            if not candidate_text:
                continue
            if _match_text(candidate_text, text, mode):
                return node
    return None


def _tap_action_from_element(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    element_id = element.get("id")
    if element_id:
        return {"type": "tap_element", "target_id": element_id}
    bounds = element.get("bounds")
    if bounds and len(bounds) == 4:
        try:
            x, y = bounds_center(bounds)
        except Exception:
            return None
        return {"type": "tap", "x": x, "y": y}
    return None


def _tap_action_from_node(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    bounds = node.get("bounds")
    if not bounds or len(bounds) != 4:
        return None
    try:
        x, y = bounds_center(bounds)
    except Exception:
        return None
    return {"type": "tap", "x": x, "y": y}


def _handle_tap_text(params: Dict[str, Any], observation) -> SkillResult:
    text = params.get("text")
    if text is None or str(text).strip() == "":
        return SkillResult(actions=[], error="tap_text requires text")
    match_mode = _normalize_match_mode(params.get("match"))
    source = _normalize_source(params.get("source"))
    if source in ("elements", "both"):
        element = _find_element_match(observation.elements, str(text).strip(), match_mode)
        if element:
            action = _tap_action_from_element(element)
            if action:
                return SkillResult(actions=[action])
    if source in ("ui", "both"):
        node = _find_ui_match(observation.ui_view, str(text).strip(), match_mode)
        if node:
            action = _tap_action_from_node(node)
            if action:
                return SkillResult(actions=[action])
    return SkillResult(actions=[], error="tap_text did not find a match")


def _handle_input_text(params: Dict[str, Any], observation) -> SkillResult:
    value = params.get("value")
    if value is None or str(value) == "":
        return SkillResult(actions=[], error="input_text requires value")
    actions: List[Dict[str, Any]] = []
    target_text = params.get("target_text")
    if target_text:
        tap_result = _handle_tap_text(
            {
                "text": target_text,
                "match": params.get("match"),
                "source": params.get("source"),
            },
            observation,
        )
        if tap_result.actions:
            actions.extend(tap_result.actions)
    actions.append({"type": "text", "value": value})
    return SkillResult(actions=actions)


def _clamp_ratio(value: float) -> float:
    if value < 0.1:
        return 0.1
    if value > 0.9:
        return 0.9
    return value


def _handle_swipe_direction(params: Dict[str, Any], observation) -> SkillResult:
    direction = str(params.get("direction") or "").strip().lower()
    if direction not in ("up", "down", "left", "right"):
        return SkillResult(actions=[], error="swipe_direction requires direction")
    try:
        distance = float(params.get("distance", 0.6))
    except (TypeError, ValueError):
        distance = 0.6
    distance = _clamp_ratio(distance)
    half = distance / 2.0
    x1 = 0.5
    y1 = 0.5
    x2 = 0.5
    y2 = 0.5
    if direction == "up":
        y1 = 0.5 + half
        y2 = 0.5 - half
    elif direction == "down":
        y1 = 0.5 - half
        y2 = 0.5 + half
    elif direction == "left":
        x1 = 0.5 + half
        x2 = 0.5 - half
    elif direction == "right":
        x1 = 0.5 - half
        x2 = 0.5 + half
    duration_ms = params.get("duration_ms", 300)
    try:
        duration_ms = int(duration_ms)
    except (TypeError, ValueError):
        duration_ms = 300
    return SkillResult(
        actions=[
            {
                "type": "swipe",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration_ms,
            }
        ]
    )


def _handle_press_key(params: Dict[str, Any], observation) -> SkillResult:
    keycode = params.get("keycode")
    if keycode is None:
        return SkillResult(actions=[], error="press_key requires keycode")
    return SkillResult(actions=[{"type": "keyevent", "keycode": keycode}])


def _handle_wait(params: Dict[str, Any], observation) -> SkillResult:
    seconds = params.get("seconds", 1)
    return SkillResult(actions=[{"type": "wait", "seconds": seconds}])


_HANDLERS = {
    "tap_text": _handle_tap_text,
    "input_text": _handle_input_text,
    "swipe_direction": _handle_swipe_direction,
    "press_key": _handle_press_key,
    "wait": _handle_wait,
}


def execute_skill(
    selection_name: Optional[str],
    params: Dict[str, Any],
    observation,
    skills: SkillLibrary,
) -> SkillResult:
    skill = skills.get(selection_name)
    if not skill:
        return SkillResult(actions=[], error="unknown skill: {}".format(selection_name))
    handler = _HANDLERS.get(skill.handler)
    if not handler:
        return SkillResult(actions=[], error="unknown skill handler: {}".format(skill.handler))
    return handler(params or {}, observation)
