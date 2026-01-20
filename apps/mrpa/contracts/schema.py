import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class SchemaError(ValueError):
    pass


@dataclass
class Action:
    type: str
    params: Dict[str, Any]
    reason: Optional[str] = None
    confidence: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Action":
        if not isinstance(data, dict):
            raise SchemaError("action must be an object")
        action_type = data.get("type")
        if not action_type:
            raise SchemaError("action missing type")
        reason = data.get("reason")
        confidence = data.get("confidence")
        params = {
            key: value
            for key, value in data.items()
            if key not in ("type", "reason", "confidence")
        }
        return cls(
            type=str(action_type),
            params=params,
            reason=reason,
            confidence=confidence,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = {"type": self.type}
        payload.update(self.params)
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass
class Decision:
    actions: List[Action]
    raw_text: Optional[str] = None
    done: bool = False
    done_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "actions": [action.to_dict() for action in self.actions],
            "done": self.done,
        }
        if self.done_reason is not None:
            payload["done_reason"] = self.done_reason
        return payload


def actions_to_dicts(actions: Iterable[Any]) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for action in actions:
        if isinstance(action, Action):
            converted.append(action.to_dict())
        elif isinstance(action, dict):
            converted.append(dict(action))
        else:
            raise SchemaError("unsupported action type {}".format(type(action)))
    return converted


_ALLOWED_ACTIONS = {"tap", "tap_element", "swipe", "text", "keyevent", "wait"}


def _has_any(action: Dict[str, Any], keys) -> bool:
    for key in keys:
        if action.get(key) is not None:
            return True
    return False


def validate_actions(actions: Iterable[Any]) -> None:
    action_list = actions_to_dicts(actions)
    for index, action in enumerate(action_list, start=1):
        action_type = action.get("type")
        if action_type not in _ALLOWED_ACTIONS:
            raise SchemaError("invalid action type {} at {}".format(action_type, index))
        if action_type == "tap":
            if _has_any(action, ("target_id", "element_id")):
                continue
            if action.get("x") is None or action.get("y") is None:
                raise SchemaError("tap missing x/y at {}".format(index))
            continue
        if action_type == "tap_element":
            if not _has_any(action, ("target_id", "element_id")):
                raise SchemaError("tap_element missing target_id at {}".format(index))
            continue
        if action_type == "swipe":
            missing = [key for key in ("x1", "y1", "x2", "y2") if action.get(key) is None]
            if missing:
                raise SchemaError(
                    "swipe missing {} at {}".format(",".join(missing), index)
                )
            continue
        if action_type == "text":
            if action.get("value") is None:
                raise SchemaError("text missing value at {}".format(index))
            continue
        if action_type == "keyevent":
            if action.get("keycode") is None:
                raise SchemaError("keyevent missing keycode at {}".format(index))
            continue
        if action_type == "wait":
            continue


def validate_actions_for_mode(actions: Iterable[Any], decision_mode: str) -> None:
    mode = (decision_mode or "").strip().lower()
    if not mode or mode == "auto":
        return
    action_list = actions_to_dicts(actions)
    for index, action in enumerate(action_list, start=1):
        action_type = action.get("type")
        if mode == "elements":
            if action_type == "tap":
                if _has_any(action, ("target_id", "element_id")):
                    if action.get("x") is not None or action.get("y") is not None:
                        raise SchemaError(
                            "tap with x/y is not allowed in elements mode at {}".format(
                                index
                            )
                        )
                    continue
                raise SchemaError(
                    "tap requires target_id/element_id in elements mode at {}".format(
                        index
                    )
                )
            continue
        if mode in ("vision", "vision_ocr"):
            if action_type == "tap_element":
                raise SchemaError(
                    "tap_element is not allowed in {} mode at {}".format(mode, index)
                )
            if _has_any(action, ("target_id", "element_id")):
                raise SchemaError(
                    "target_id/element_id is not allowed in {} mode at {}".format(
                        mode, index
                    )
                )


def _extract_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise SchemaError("model response did not include JSON")
    return match.group(0)


_DECISION_VALIDATOR = None
_OBSERVATION_VALIDATOR = None


def _get_decision_validator():
    global _DECISION_VALIDATOR
    if _DECISION_VALIDATOR is None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise SchemaError("jsonschema is required for decision validation") from exc
        schema_path = Path(__file__).with_name("decision.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        _DECISION_VALIDATOR = Draft202012Validator(schema)
    return _DECISION_VALIDATOR


def _get_observation_validator():
    global _OBSERVATION_VALIDATOR
    if _OBSERVATION_VALIDATOR is None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise SchemaError("jsonschema is required for observation validation") from exc
        schema_path = Path(__file__).with_name("observation.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        _OBSERVATION_VALIDATOR = Draft202012Validator(schema)
    return _OBSERVATION_VALIDATOR


def _format_schema_path(path) -> str:
    if not path:
        return "$"
    parts = ["$"]
    for item in path:
        if isinstance(item, int):
            parts.append("[{}]".format(item))
        else:
            parts.append(".{}".format(item))
    return "".join(parts)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "y"):
            return True
        if lowered in ("false", "0", "no", "n"):
            return False
    return False


def parse_decision_text(text: str) -> Decision:
    json_text = _extract_json(text)
    data = json.loads(json_text)
    validator = _get_decision_validator()
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = _format_schema_path(error.path)
        raise SchemaError(
            "decision JSON schema validation failed at {}: {}".format(
                location, error.message
            )
        )
    done = _coerce_bool(data.get("done"))
    done_reason = data.get("done_reason") or data.get("doneReason")
    actions = data.get("actions")
    if actions is None:
        if done:
            actions = []
        else:
            raise SchemaError("model response missing actions list")
    if not isinstance(actions, list):
        raise SchemaError("model response missing actions list")
    parsed = [Action.from_dict(item) for item in actions]
    if done:
        parsed = []
    return Decision(actions=parsed, raw_text=text, done=done, done_reason=done_reason)


def validate_observation_context(context: Dict[str, Any]) -> None:
    validator = _get_observation_validator()
    errors = sorted(validator.iter_errors(context), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = _format_schema_path(error.path)
        raise SchemaError(
            "observation schema validation failed at {}: {}".format(
                location, error.message
            )
        )
