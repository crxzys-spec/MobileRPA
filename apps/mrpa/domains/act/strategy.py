import time

from mrpa.contracts import SchemaError, actions_to_dicts
from mrpa.domains.ports import DeviceClient
from shared.errors import AdbError
from shared.utils.geometry import bounds_center, clamp, scale_coord


def normalize_keycode(value):
    if value is None:
        raise AdbError("keyevent missing keycode")
    if isinstance(value, int):
        return value
    value = str(value).strip()
    if not value:
        raise AdbError("keyevent missing keycode")
    keycode_map = {
        "KEYCODE_POWER": 26,
        "KEYCODE_VOLUME_UP": 24,
        "KEYCODE_VOLUME_DOWN": 25,
        "KEYCODE_BACK": 4,
        "KEYCODE_HOME": 3,
        "KEYCODE_APP_SWITCH": 187,
        "KEYCODE_MENU": 82,
        "KEYCODE_ENTER": 66,
        "KEYCODE_DEL": 67,
        "KEYCODE_ESCAPE": 111,
    }
    mapped = keycode_map.get(value.upper())
    if mapped is not None:
        return mapped
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return value
    return value


def execute_actions(adb: DeviceClient, actions, width, height, log=None, elements=None):
    try:
        action_list = actions_to_dicts(actions)
    except SchemaError as exc:
        raise AdbError(str(exc)) from exc
    element_map = {}
    if elements:
        element_map = {
            element.get("id"): element
            for element in elements
            if element.get("id") is not None
        }
    for index, action in enumerate(action_list, start=1):
        action_type = action.get("type")
        target_id = action.get("target_id") or action.get("element_id")
        if action_type == "tap":
            if target_id:
                element = element_map.get(target_id)
                if not element:
                    raise AdbError("unknown target_id {}".format(target_id))
                bounds = element.get("bounds")
                if bounds:
                    x, y = bounds_center(bounds)
                else:
                    x = clamp(scale_coord(element.get("x"), width), 0, width - 1)
                    y = clamp(scale_coord(element.get("y"), height), 0, height - 1)
            else:
                x = clamp(scale_coord(action.get("x"), width), 0, width - 1)
                y = clamp(scale_coord(action.get("y"), height), 0, height - 1)
            if log:
                log("action {}: tap x={} y={}".format(index, x, y))
            adb.tap(x, y)
            continue
        if action_type == "tap_element":
            if not target_id:
                raise AdbError("action {} missing target_id".format(index))
            element = element_map.get(target_id)
            if not element:
                raise AdbError("unknown target_id {}".format(target_id))
            bounds = element.get("bounds")
            if not bounds:
                raise AdbError("target {} missing bounds".format(target_id))
            x, y = bounds_center(bounds)
            if log:
                log("action {}: tap_element {} x={} y={}".format(index, target_id, x, y))
            adb.tap(x, y)
            continue
        if action_type == "swipe":
            x1 = clamp(scale_coord(action.get("x1"), width), 0, width - 1)
            y1 = clamp(scale_coord(action.get("y1"), height), 0, height - 1)
            x2 = clamp(scale_coord(action.get("x2"), width), 0, width - 1)
            y2 = clamp(scale_coord(action.get("y2"), height), 0, height - 1)
            duration_ms = int(action.get("duration_ms", 300))
            if log:
                log(
                    "action {}: swipe x1={} y1={} x2={} y2={} duration_ms={}".format(
                        index, x1, y1, x2, y2, duration_ms
                    )
                )
            adb.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
            continue
        if action_type == "text":
            value = action.get("value")
            if value is None:
                raise AdbError("action {} missing text value".format(index))
            if target_id:
                element = element_map.get(target_id)
                if not element:
                    raise AdbError("unknown target_id {}".format(target_id))
                bounds = element.get("bounds")
                if bounds:
                    x, y = bounds_center(bounds)
                    adb.tap(x, y)
            if log:
                log("action {}: text value={}".format(index, value))
            adb.input_text(str(value))
            continue
        if action_type == "keyevent":
            keycode = normalize_keycode(action.get("keycode"))
            if log:
                log("action {}: keyevent code={}".format(index, keycode))
            adb.keyevent(keycode)
            continue
        if action_type == "wait":
            seconds = float(action.get("seconds", 1))
            if log:
                log("action {}: wait seconds={}".format(index, seconds))
            time.sleep(seconds)
            continue
        raise AdbError("unsupported action type {} at {}".format(action_type, index))
