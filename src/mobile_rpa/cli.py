import argparse
import asyncio
import base64
import inspect
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

from mobile_rpa.settings import load_settings


UI_DUMP_PATH = "/sdcard/uidump.xml"
WECHAT_PACKAGE = "com.tencent.mm"
WECHAT_ACTIVITY = "com.tencent.mm.ui.LauncherUI"
_OCR_CACHE = {}


os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")


class AdbError(RuntimeError):
    pass


def adb_text_escape(text):
    escaped = []
    for ch in text:
        if ch == " ":
            escaped.append("%s")
        elif ch in "\\'\"&|<>;()$`":
            escaped.append("\\" + ch)
        else:
            escaped.append(ch)
    return "".join(escaped)


def parse_bounds(bounds):
    match = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    left, top, right, bottom = (int(group) for group in match.groups())
    return left, top, right, bottom


def center_of(bounds):
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def ensure_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise AdbError(
            "opencv-python is required for image recognition. "
            "Install with pip install -r requirements.txt"
        ) from exc
    return cv2, np


def ensure_paddleocr(
    lang="ch",
    use_gpu=False,
    allow_cpu_fallback=True,
    extra_kwargs=None,
):
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise AdbError(
            "paddleocr is required for OCR. Install with pip install -r requirements.txt"
        ) from exc
    if not use_gpu:
        os.environ.setdefault("FLAGS_use_mkldnn", "0")
        os.environ.setdefault("FLAGS_enable_mkldnn", "0")
        os.environ.setdefault("FLAGS_enable_pir_api", "0")
        os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")
        os.environ.setdefault("PADDLE_DISABLE_PIR", "1")
    try:
        import paddle

        if use_gpu and hasattr(paddle, "is_compiled_with_cuda"):
            if not paddle.is_compiled_with_cuda():
                if allow_cpu_fallback:
                    use_gpu = False
                else:
                    raise AdbError(
                        "Paddle is not compiled with CUDA. Install paddlepaddle-gpu."
                    )
        if not use_gpu:
            os.environ.setdefault("FLAGS_use_mkldnn", "0")
            os.environ.setdefault("FLAGS_enable_mkldnn", "0")
            os.environ.setdefault("FLAGS_enable_pir_api", "0")
            os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")
            os.environ.setdefault("PADDLE_DISABLE_PIR", "1")
        if use_gpu:
            try:
                paddle.set_device("gpu")
            except Exception:
                pass
        if not use_gpu:
            paddle.set_flags({"FLAGS_use_mkldnn": 0})
            paddle.set_flags({"FLAGS_enable_mkldnn": 0})
            paddle.set_flags({"FLAGS_enable_pir_api": 0})
            paddle.set_flags({"FLAGS_enable_pir_in_executor": 0})
    except Exception:
        pass
    cache_key = "lang={} gpu={}".format(lang, use_gpu)
    if cache_key not in _OCR_CACHE:
        try:
            sig = inspect.signature(PaddleOCR.__init__)
            params = sig.parameters
            accepts_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in params.values()
            )
        except (TypeError, ValueError):
            params = {}
            accepts_kwargs = True

        def allow_kwargs(kwargs):
            if accepts_kwargs:
                return kwargs
            return {key: value for key, value in kwargs.items() if key in params}

        base_kwargs = {"lang": lang}
        if use_gpu:
            if "use_gpu" in params:
                base_kwargs["use_gpu"] = True
            elif "device" in params:
                base_kwargs["device"] = "gpu"
        else:
            if "use_gpu" in params:
                base_kwargs["use_gpu"] = False
            elif "device" in params:
                base_kwargs["device"] = "cpu"

        if "use_doc_orientation_classify" in params:
            base_kwargs["use_doc_orientation_classify"] = False
        if "use_doc_unwarping" in params:
            base_kwargs["use_doc_unwarping"] = False
        if "use_textline_orientation" in params:
            base_kwargs["use_textline_orientation"] = False

        candidates = []
        if extra_kwargs:
            merged = dict(base_kwargs)
            merged.update(extra_kwargs)
            candidates.append(allow_kwargs(merged))
        candidates.append(allow_kwargs(base_kwargs))

        minimal = {"lang": lang}
        if use_gpu:
            if "use_gpu" in params:
                minimal["use_gpu"] = True
            elif "device" in params:
                minimal["device"] = "gpu"
        else:
            if "use_gpu" in params:
                minimal["use_gpu"] = False
            elif "device" in params:
                minimal["device"] = "cpu"
        candidates.append(allow_kwargs(minimal))

        last_error = None
        for kwargs in candidates:
            try:
                _OCR_CACHE[cache_key] = PaddleOCR(**kwargs)
                last_error = None
                break
            except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
                last_error = exc
        if cache_key not in _OCR_CACHE:
            raise AdbError("failed to initialize PaddleOCR: {}".format(last_error))
    return _OCR_CACHE[cache_key]


def ensure_aiohttp():
    try:
        import aiohttp
    except ImportError as exc:
        raise AdbError(
            "aiohttp is required for remote OCR. Install with pip install aiohttp"
        ) from exc
    return aiohttp


async def remote_ocr_request(
    url,
    png_bytes,
    lang="ch",
    score_threshold=0.5,
    timeout=30,
    api_key=None,
    device=None,
):
    aiohttp = ensure_aiohttp()
    data = aiohttp.FormData()
    data.add_field(
        "image",
        png_bytes,
        filename="screen.png",
        content_type="image/png",
    )
    data.add_field("lang", str(lang))
    data.add_field("threshold", str(score_threshold))
    if device:
        data.add_field("device", str(device))
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(url, data=data, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise AdbError(
                        "remote OCR failed: {} {}".format(resp.status, text.strip())
                    )
    except aiohttp.ClientError as exc:
        raise AdbError("remote OCR request failed: {}".format(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise AdbError("remote OCR request timed out") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdbError("remote OCR returned invalid JSON") from exc


def decode_png(png_bytes):
    cv2, np = ensure_cv2()
    data = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise AdbError("failed to decode screenshot")
    return image


def load_image(path):
    cv2, _ = ensure_cv2()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise AdbError("failed to load image: {}".format(path))
    return image


def png_size(png_bytes):
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise AdbError("image is not a valid PNG")
    width, height = struct.unpack(">II", png_bytes[16:24])
    return int(width), int(height)


def encode_png(image):
    cv2, _ = ensure_cv2()
    success, buffer = cv2.imencode(".png", image)
    if not success:
        raise AdbError("failed to encode PNG")
    return buffer.tobytes()


def parse_wm_size(output):
    override = None
    physical = None
    for line in output.splitlines():
        if "Override size" in line:
            match = re.search(r"(\d+)x(\d+)", line)
            if match:
                override = (int(match.group(1)), int(match.group(2)))
        if "Physical size" in line:
            match = re.search(r"(\d+)x(\d+)", line)
            if match:
                physical = (int(match.group(1)), int(match.group(2)))
    return override or physical


def parse_wm_density(output):
    for line in output.splitlines():
        if "Physical density" in line or "Override density" in line:
            match = re.search(r"(\d+)", line)
            if match:
                return int(match.group(1))
    return None


def normalize_region(region):
    if not region:
        return None
    if isinstance(region, str):
        parts = [part.strip() for part in region.split(",") if part.strip()]
        if len(parts) != 4:
            raise AdbError("region must be x1,y1,x2,y2")
        return tuple(int(part) for part in parts)
    if isinstance(region, (list, tuple)):
        if len(region) != 4:
            raise AdbError("region must have 4 values")
        return tuple(int(value) for value in region)
    if isinstance(region, dict):
        if all(key in region for key in ("x1", "y1", "x2", "y2")):
            return tuple(int(region[key]) for key in ("x1", "y1", "x2", "y2"))
        if all(key in region for key in ("x", "y", "w", "h")):
            left = int(region["x"])
            top = int(region["y"])
            return left, top, left + int(region["w"]), top + int(region["h"])
    raise AdbError("invalid region")


def parse_offset(offset):
    if not offset:
        return 0, 0
    if isinstance(offset, str):
        parts = [part.strip() for part in offset.split(",") if part.strip()]
        if len(parts) != 2:
            raise AdbError("offset must be dx,dy")
        return int(parts[0]), int(parts[1])
    if isinstance(offset, (list, tuple)) and len(offset) == 2:
        return int(offset[0]), int(offset[1])
    if isinstance(offset, dict):
        return int(offset.get("x", 0)), int(offset.get("y", 0))
    raise AdbError("invalid offset")


def capture_screen(adb):
    return decode_png(adb.screenshot_bytes())


def match_template(screen, template, region=None):
    cv2, _ = ensure_cv2()
    screen_height, screen_width = screen.shape[:2]
    if region:
        left, top, right, bottom = region
    else:
        left, top, right, bottom = 0, 0, screen_width, screen_height
    if right <= left or bottom <= top:
        raise AdbError("invalid region bounds")
    region_img = screen[top:bottom, left:right]
    template_height, template_width = template.shape[:2]
    region_height, region_width = region_img.shape[:2]
    if template_height > region_height or template_width > region_width:
        raise AdbError("template larger than search region")
    result = cv2.matchTemplate(region_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    top_left = (left + max_loc[0], top + max_loc[1])
    return {
        "score": float(max_val),
        "top_left": top_left,
        "size": (template_width, template_height),
    }


def match_center(match):
    left, top = match["top_left"]
    width, height = match["size"]
    return left + width // 2, top + height // 2


def find_image(adb, image_path, threshold=0.85, region=None):
    screen = capture_screen(adb)
    template = load_image(image_path)
    match = match_template(screen, template, region=region)
    if match["score"] >= threshold:
        return match
    return None


def wait_for_image(
    adb,
    image_path,
    threshold=0.85,
    timeout=10,
    interval=0.5,
    region=None,
):
    template = load_image(image_path)
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screen(adb)
        match = match_template(screen, template, region=region)
        if match["score"] >= threshold:
            return match
        time.sleep(interval)
    return None


def build_vision_prompt(goal, max_actions, width, height):
    return (
        "You are an Android UI assistant. Analyze the screenshot and propose "
        "the next UI actions to achieve the goal.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "actions": [\n'
        '    {{"type": "tap", "x": 0.5, "y": 0.5, "reason": "...", "confidence": 0.0}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        "- Coordinates are normalized (0..1) relative to image size.\n"
        "- 0,0 is top-left; 1,1 is bottom-right.\n"
        '- Allowed types: "tap", "swipe", "text", "keyevent", "wait".\n'
        "- For swipe, use x1,y1,x2,y2 and optional duration_ms.\n"
        "- For text, use value; for keyevent, use keycode; for wait, use seconds.\n"
        "- At most {max_actions} actions.\n"
        "- If unsure, return an empty actions list.\n"
        "Goal: {goal}\n"
        "Image size: {width}x{height}\n"
    ).format(max_actions=max_actions, goal=goal, width=width, height=height)


def build_vision_label_prompt(goal, max_elements, width, height):
    return (
        "You are an Android UI analyst. Identify visible UI elements in the screenshot "
        "and return their bounding boxes with labels.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "elements": [\n'
        '    {{"label": "Search", "type": "button", "x1": 0.1, "y1": 0.1, '
        '"x2": 0.2, "y2": 0.2, "description": "...", "confidence": 0.0}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        "- Coordinates are normalized (0..1) relative to image size.\n"
        "- 0,0 is top-left; 1,1 is bottom-right.\n"
        '- type should be one of: "button", "icon", "text", "input", "list", '
        '"tab", "image", "unknown".\n'
        "- At most {max_elements} elements.\n"
        "- If unsure, return an empty elements list.\n"
        "Goal context: {goal}\n"
        "Image size: {width}x{height}\n"
    ).format(max_elements=max_elements, goal=goal, width=width, height=height)


def build_decision_prompt(goal, elements, max_actions):
    lines = []
    for element in elements:
        element_id = element.get("id", "")
        element_type = element.get("type", "unknown")
        text = element.get("text", "")
        bounds = element.get("bounds")
        center = element.get("center")
        confidence = element.get("confidence")
        source = element.get("source", "")
        lines.append(
            "id={id} type={type} text={text} bounds={bounds} center={center} "
            "confidence={conf} source={source}".format(
                id=element_id,
                type=element_type,
                text=text,
                bounds=bounds,
                center=center,
                conf=confidence,
                source=source,
            )
        )
    elements_text = "\n".join(lines) if lines else "(no elements)"
    return (
        "You are an Android UI decision assistant. Choose the next actions to "
        "achieve the goal based on the provided UI elements.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "actions": [\n'
        '    {{"type": "tap_element", "target_id": "id", "reason": "...", "confidence": 0.0}},\n'
        '    {{"type": "text", "value": "..."}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        '- Allowed types: "tap_element", "tap", "swipe", "text", "keyevent", "wait".\n'
        '- For tap_element, use target_id from the element list.\n'
        '- For tap, use x/y or target_id.\n'
        "- For swipe, use x1,y1,x2,y2 and optional duration_ms.\n"
        "- For text, use value. For keyevent, use keycode.\n"
        "- At most {max_actions} actions.\n"
        "- If unsure, return an empty actions list.\n"
        "Goal: {goal}\n"
        "Elements:\n"
        "{elements}\n"
    ).format(max_actions=max_actions, goal=goal, elements=elements_text)


def call_openai_vision(api_key, model, prompt, png_bytes, temperature=0.2, timeout=60):
    if not api_key:
        raise AdbError("OPENAI_API_KEY is not set")
    image_b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {
                "role": "system",
                "content": "Return JSON only, no extra text.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,{}".format(image_b64)},
                    },
                ],
            },
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer {}".format(api_key),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise AdbError("openai api error {}: {}".format(err.code, detail))
    data = json.loads(body.decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return content


def call_openai_text(api_key, model, prompt, temperature=0.2, timeout=60):
    if not api_key:
        raise AdbError("OPENAI_API_KEY is not set")
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": "Return JSON only, no extra text."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer {}".format(api_key),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise AdbError("openai api error {}: {}".format(err.code, detail))
    data = json.loads(body.decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return content


def extract_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise AdbError("model response did not include JSON")
    return match.group(0)


def parse_actions_json(text):
    json_text = extract_json(text)
    data = json.loads(json_text)
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise AdbError("model response missing actions list")
    return actions


def parse_elements_json(text):
    json_text = extract_json(text)
    data = json.loads(json_text)
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise AdbError("model response missing elements list")
    return elements


def coerce_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AdbError("invalid {} value".format(label)) from exc


def scale_coord(value, max_value):
    coord = coerce_float(value, "coordinate")
    if 0 <= coord <= 1:
        coord = coord * max_value
    return int(round(coord))


def clamp(value, low, high):
    return max(low, min(high, value))


def resolve_region(region, width, height):
    if not region:
        return None

    def to_abs(value, max_value):
        value = float(value)
        if 0 <= value <= 1:
            return int(round(value * max_value))
        return int(round(value))

    if isinstance(region, str):
        parts = [part.strip() for part in region.split(",") if part.strip()]
        if len(parts) != 4:
            raise AdbError("region must be x1,y1,x2,y2")
        left = to_abs(parts[0], width)
        top = to_abs(parts[1], height)
        right = to_abs(parts[2], width)
        bottom = to_abs(parts[3], height)
    elif isinstance(region, (list, tuple)):
        if len(region) != 4:
            raise AdbError("region must have 4 values")
        left = to_abs(region[0], width)
        top = to_abs(region[1], height)
        right = to_abs(region[2], width)
        bottom = to_abs(region[3], height)
    elif isinstance(region, dict):
        if all(key in region for key in ("x1", "y1", "x2", "y2")):
            left = to_abs(region["x1"], width)
            top = to_abs(region["y1"], height)
            right = to_abs(region["x2"], width)
            bottom = to_abs(region["y2"], height)
        elif all(key in region for key in ("x", "y", "w", "h")):
            left = to_abs(region["x"], width)
            top = to_abs(region["y"], height)
            region_width = to_abs(region["w"], width)
            region_height = to_abs(region["h"], height)
            right = left + region_width
            bottom = top + region_height
        else:
            raise AdbError("invalid region keys")
    else:
        raise AdbError("invalid region")

    left = clamp(left, 0, width - 1)
    top = clamp(top, 0, height - 1)
    right = clamp(right, left + 1, width)
    bottom = clamp(bottom, top + 1, height)
    return left, top, right, bottom


def crop_image(image, region):
    if not region:
        return image, None
    left, top, right, bottom = region
    return image[top:bottom, left:right], (left, top)


def offset_bounds(bounds, offset):
    if not offset:
        return bounds
    dx, dy = offset
    return [bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy]


def offset_elements(elements, offset):
    if not offset:
        return elements
    dx, dy = offset
    for element in elements:
        bounds = element.get("bounds")
        if not bounds or len(bounds) != 4:
            continue
        updated = [bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy]
        element["bounds"] = updated
        center_x, center_y = bounds_center(updated)
        element["center"] = [center_x, center_y]
    return elements


def bounds_center(bounds):
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def unique_id(base, used):
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


def collect_template_paths(template_dir):
    if not template_dir:
        return []
    base = Path(template_dir)
    if not base.exists():
        return []
    patterns = ("*.png", "*.jpg", "*.jpeg", "*.bmp")
    paths = []
    for pattern in patterns:
        paths.extend(base.glob(pattern))
    return sorted(paths)


def detect_templates(screen, template_dir, threshold=0.85, offset=None):
    templates = collect_template_paths(template_dir)
    if not templates:
        return []
    elements = []
    used_ids = set()
    for template_path in templates:
        template = load_image(template_path)
        match = match_template(screen, template, region=None)
        if match["score"] < threshold:
            continue
        left, top = match["top_left"]
        width, height = match["size"]
        bounds = [left, top, left + width, top + height]
        bounds = offset_bounds(bounds, offset)
        element_id = unique_id("tpl:{}".format(template_path.stem), used_ids)
        center_x, center_y = bounds_center(bounds)
        elements.append(
            {
                "id": element_id,
                "type": "icon",
                "text": "",
                "bounds": bounds,
                "center": [center_x, center_y],
                "confidence": round(match["score"], 3),
                "source": "template:{}".format(template_path.as_posix()),
            }
        )
    return elements


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


def _get_value(mapping, keys, default):
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None:
                return value
    return default


def bounds_from_box(box):
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


def parse_ocr_result(result, score_threshold=0.5, offset=None):
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
    elements = []
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
                    bounds = bounds_from_box(polys[i])
                elif boxes and i < len(boxes):
                    box = boxes[i]
                    try:
                        bounds = [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
                    except Exception:
                        bounds = None
                if not bounds:
                    continue
                bounds = offset_bounds(bounds, offset)
                index += 1
                element_id = unique_id("ocr:{}".format(index), used_ids)
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
                score = (
                    text_data.get("score") or text_data.get("confidence") or 1.0
                )
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
        bounds = bounds_from_box(box)
        if not bounds:
            continue
        bounds = offset_bounds(bounds, offset)
        index += 1
        element_id = unique_id("ocr:{}".format(index), used_ids)
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


def run_ocr(ocr, screen):
    if hasattr(ocr, "predict"):
        try:
            sig = inspect.signature(ocr.predict)
        except (TypeError, ValueError):
            return ocr.predict(screen)
        if "input" in sig.parameters:
            return ocr.predict(input=screen)
        return ocr.predict(screen)
    return ocr.ocr(screen)


def ocr_elements(
    screen,
    lang="ch",
    score_threshold=0.5,
    offset=None,
    use_gpu=False,
    allow_cpu_fallback=True,
    ocr_kwargs=None,
):
    ocr = ensure_paddleocr(
        lang=lang,
        use_gpu=use_gpu,
        allow_cpu_fallback=allow_cpu_fallback,
        extra_kwargs=ocr_kwargs,
    )
    try:
        result = run_ocr(ocr, screen)
    except NotImplementedError as exc:
        raise AdbError(
            "PaddleOCR backend failed. Check your paddlepaddle install and "
            "verify GPU/CPU compatibility."
        ) from exc
    elements = parse_ocr_result(result, score_threshold=score_threshold, offset=offset)
    if use_gpu and allow_cpu_fallback and not elements:
        ocr_cpu = ensure_paddleocr(
            lang=lang,
            use_gpu=False,
            allow_cpu_fallback=True,
            extra_kwargs=ocr_kwargs,
        )
        result = run_ocr(ocr_cpu, screen)
        elements = parse_ocr_result(
            result, score_threshold=score_threshold, offset=offset
        )
        if elements:
            print("warning: GPU OCR returned 0 boxes; fell back to CPU", file=sys.stderr)
    return elements


def ocr_elements_remote(
    screen,
    url,
    lang="ch",
    score_threshold=0.5,
    offset=None,
    timeout=30,
    api_key=None,
    device=None,
):
    if not url:
        raise AdbError("remote OCR endpoint is not configured")
    png_bytes = encode_png(screen)
    payload = asyncio.run(
        remote_ocr_request(
            url,
            png_bytes,
            lang=lang,
            score_threshold=score_threshold,
            timeout=timeout,
            api_key=api_key,
            device=device,
        )
    )
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise AdbError("remote OCR returned unexpected payload")
    return offset_elements(elements, offset)


def detect_elements(
    adb,
    image_path=None,
    template_dir=None,
    template_threshold=0.85,
    use_ocr=True,
    ocr_lang="ch",
    ocr_threshold=0.5,
    ocr_provider="remote",
    ocr_remote_url=None,
    ocr_remote_timeout=30,
    ocr_remote_api_key=None,
    ocr_remote_device=None,
    ocr_use_gpu=False,
    ocr_allow_cpu_fallback=True,
    ocr_kwargs=None,
    region=None,
):
    png_bytes, width, height = get_png_bytes(adb, image_path)
    screen = decode_png(png_bytes)
    crop_region = resolve_region(region, width, height)
    cropped = screen
    offset = None
    if crop_region:
        cropped, offset = crop_image(screen, crop_region)
    elements = []
    elements.extend(detect_templates(cropped, template_dir, template_threshold, offset))
    if use_ocr:
        if ocr_provider == "remote":
            elements.extend(
                ocr_elements_remote(
                    cropped,
                    url=ocr_remote_url,
                    lang=ocr_lang,
                    score_threshold=ocr_threshold,
                    offset=offset,
                    timeout=ocr_remote_timeout,
                    api_key=ocr_remote_api_key,
                    device=ocr_remote_device,
                )
            )
        else:
            elements.extend(
                ocr_elements(
                    cropped,
                    lang=ocr_lang,
                    score_threshold=ocr_threshold,
                    offset=offset,
                    use_gpu=ocr_use_gpu,
                    allow_cpu_fallback=ocr_allow_cpu_fallback,
                    ocr_kwargs=ocr_kwargs,
                )
            )
    return elements, width, height, png_bytes, crop_region


def execute_actions(adb, actions, width, height, log=None, elements=None):
    element_map = {}
    if elements:
        element_map = {
            element.get("id"): element
            for element in elements
            if element.get("id") is not None
        }
    for index, action in enumerate(actions, start=1):
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
            keycode = action.get("keycode")
            if keycode is None:
                raise AdbError("action {} missing keycode".format(index))
            if log:
                log("action {}: keyevent code={}".format(index, keycode))
            adb.keyevent(int(keycode))
            continue
        if action_type == "wait":
            seconds = float(action.get("seconds", 1))
            if log:
                log("action {}: wait seconds={}".format(index, seconds))
            time.sleep(seconds)
            continue
        raise AdbError("unsupported action type {} at {}".format(action_type, index))


def get_png_bytes(adb, image_path):
    if image_path:
        png_bytes = Path(image_path).read_bytes()
    else:
        png_bytes = adb.screenshot_bytes()
    width, height = png_size(png_bytes)
    return png_bytes, width, height


def adjust_actions_for_region(actions, region, full_width, full_height):
    if not region:
        return actions
    left, top, right, bottom = region
    region_width = right - left
    region_height = bottom - top
    adjusted = []
    for action in actions:
        action_type = action.get("type")
        updated = dict(action)
        if action_type == "tap":
            x = action.get("x")
            y = action.get("y")
            if x is None or y is None:
                adjusted.append(updated)
                continue
            x_abs = left + (x * region_width if 0 <= x <= 1 else x)
            y_abs = top + (y * region_height if 0 <= y <= 1 else y)
            updated["x"] = round(float(x_abs), 2)
            updated["y"] = round(float(y_abs), 2)
        elif action_type == "swipe":
            for key, size, offset in (
                ("x1", region_width, left),
                ("y1", region_height, top),
                ("x2", region_width, left),
                ("y2", region_height, top),
            ):
                value = updated.get(key)
                if value is None:
                    continue
                abs_value = offset + (value * size if 0 <= value <= 1 else value)
                updated[key] = round(float(abs_value), 2)
        adjusted.append(updated)
    return adjusted


def adjust_elements_for_region(elements, region, full_width, full_height):
    if not region:
        return elements
    left, top, right, bottom = region
    region_width = right - left
    region_height = bottom - top
    adjusted = []
    for element in elements:
        updated = dict(element)
        for key, size, offset in (
            ("x1", region_width, left),
            ("y1", region_height, top),
            ("x2", region_width, left),
            ("y2", region_height, top),
        ):
            value = updated.get(key)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            abs_value = offset + (numeric * size if 0 <= numeric <= 1 else numeric)
            updated[key] = round(float(abs_value), 2)
        adjusted.append(updated)
    return adjusted


def elements_to_pixels(elements, width, height):
    converted = []
    for element in elements:
        updated = dict(element)
        for key, max_value in (
            ("x1", width),
            ("x2", width),
            ("y1", height),
            ("y2", height),
        ):
            value = updated.get(key)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if 0 <= numeric <= 1:
                numeric = numeric * max_value
            numeric = clamp(int(round(numeric)), 0, max_value - 1)
            updated[key] = numeric
        converted.append(updated)
    return converted


def draw_label(image, text, x, y, color):
    cv2, _ = ensure_cv2()
    height, width = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.6
    thickness = 2
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    x = clamp(x, 0, max(0, width - text_width - 1))
    y = clamp(y, text_height + baseline, max(text_height + baseline, height - 1))
    cv2.putText(
        image,
        text,
        (x, y),
        font,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def annotate_actions(image, actions, width, height):
    cv2, _ = ensure_cv2()
    colors = [
        (0, 0, 255),
        (0, 128, 255),
        (0, 200, 0),
        (255, 128, 0),
        (255, 0, 255),
    ]
    text_actions = []
    for index, action in enumerate(actions, start=1):
        action_type = action.get("type")
        color = colors[(index - 1) % len(colors)]
        if action_type == "tap":
            x = clamp(scale_coord(action.get("x"), width), 0, width - 1)
            y = clamp(scale_coord(action.get("y"), height), 0, height - 1)
            cv2.circle(image, (x, y), 16, color, 2)
            cv2.circle(image, (x, y), 3, color, -1)
            draw_label(image, str(index), x + 10, y - 10, color)
            continue
        if action_type == "swipe":
            x1 = clamp(scale_coord(action.get("x1"), width), 0, width - 1)
            y1 = clamp(scale_coord(action.get("y1"), height), 0, height - 1)
            x2 = clamp(scale_coord(action.get("x2"), width), 0, width - 1)
            y2 = clamp(scale_coord(action.get("y2"), height), 0, height - 1)
            cv2.arrowedLine(image, (x1, y1), (x2, y2), color, 2, tipLength=0.2)
            draw_label(image, str(index), x1 + 10, y1 - 10, color)
            continue
        if action_type:
            text_actions.append("{}:{}".format(index, action_type))
    if text_actions:
        start_y = 30
        for offset, item in enumerate(text_actions):
            draw_label(image, item, 10, start_y + offset * 24, (255, 255, 255))


def annotate_elements(image, elements, width, height):
    cv2, _ = ensure_cv2()
    colors = [
        (0, 255, 0),
        (0, 255, 255),
        (255, 0, 0),
        (255, 128, 0),
        (255, 0, 255),
    ]
    for index, element in enumerate(elements, start=1):
        color = colors[(index - 1) % len(colors)]
        x1 = clamp(scale_coord(element.get("x1"), width), 0, width - 1)
        y1 = clamp(scale_coord(element.get("y1"), height), 0, height - 1)
        x2 = clamp(scale_coord(element.get("x2"), width), 0, width - 1)
        y2 = clamp(scale_coord(element.get("y2"), height), 0, height - 1)
        if x2 <= x1 or y2 <= y1:
            continue
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = element.get("label") or element.get("type") or "element"
        draw_label(image, "{} {}".format(index, label), x1 + 6, y1 + 22, color)


def save_image(path, image):
    cv2, _ = ensure_cv2()
    output_path = Path(path)
    if output_path.parent and not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        raise AdbError("failed to write image: {}".format(output_path))


class AdbClient:
    def __init__(self, adb_path="adb", device_id=None):
        self.adb_path = adb_path
        self.device_id = device_id or None

    def _base_cmd(self):
        cmd = [self.adb_path]
        if self.device_id:
            cmd += ["-s", self.device_id]
        return cmd

    def run(self, args, timeout=30, check=True, text=True, input_data=None):
        cmd = self._base_cmd() + list(args)
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            timeout=timeout,
            text=text,
        )
        if check and result.returncode != 0:
            raise AdbError(
                "adb failed: {}\n{}".format(" ".join(cmd), result.stderr.strip())
            )
        return result

    def devices(self):
        return [
            device_id
            for device_id, status in self.list_devices()
            if status == "device"
        ]

    def list_devices(self):
        output = self.run(["devices"], timeout=10).stdout.splitlines()
        devices = []
        for line in output[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
        return devices

    def shell(self, cmd, timeout=30, check=True):
        if isinstance(cmd, str):
            args = ["shell", cmd]
        else:
            args = ["shell"] + list(cmd)
        return self.run(args, timeout=timeout, check=check)

    def exec_out(self, cmd, timeout=30):
        if isinstance(cmd, str):
            args = ["exec-out", cmd]
        else:
            args = ["exec-out"] + list(cmd)
        return self.run(args, timeout=timeout, check=True, text=False)

    def wait_for_device(self, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            if self.devices():
                return
            time.sleep(1)
        raise AdbError("no adb devices found")

    def tap(self, x, y):
        self.shell(["input", "tap", str(x), str(y)])

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.shell(
            [
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ]
        )

    def keyevent(self, keycode):
        self.shell(["input", "keyevent", str(keycode)])

    def input_text(self, text):
        escaped = adb_text_escape(text)
        self.shell(["input", "text", escaped])

    def start_app(self, package, activity=None):
        if activity:
            self.shell(["am", "start", "-n", "{}/{}".format(package, activity)])
        else:
            self.shell(
                [
                    "monkey",
                    "-p",
                    package,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ]
            )

    def screenshot(self, output_path):
        Path(output_path).write_bytes(self.screenshot_bytes())

    def screenshot_bytes(self):
        result = self.exec_out(["screencap", "-p"])
        return result.stdout

    def _dump_ui_direct(self):
        candidates = [
            ["uiautomator", "dump", "--compressed", "/dev/tty"],
            ["uiautomator", "dump", "/dev/tty"],
        ]
        for args in candidates:
            try:
                result = self.exec_out(args, timeout=30)
            except AdbError:
                continue
            xml_text = result.stdout.decode("utf-8", errors="replace")
            extracted = extract_hierarchy(xml_text)
            if extracted:
                return extracted
        return None

    def dump_ui(self):
        xml_text = self._dump_ui_direct()
        if xml_text:
            return xml_text
        self.shell(["uiautomator", "dump", UI_DUMP_PATH])
        result = self.exec_out(["cat", UI_DUMP_PATH])
        extracted = extract_hierarchy(
            result.stdout.decode("utf-8", errors="replace")
        )
        if not extracted:
            raise AdbError("failed to extract UI hierarchy")
        return extracted


def extract_hierarchy(xml_text):
    if not xml_text:
        return None
    xml_text = xml_text.replace("\x00", "")
    match = re.search(r"<hierarchy[^>]*>.*</hierarchy>", xml_text, re.DOTALL)
    if not match:
        return None
    return match.group(0).strip()


def iter_nodes(xml_text):
    root = ET.fromstring(xml_text)
    for node in root.iter():
        if node.tag != "node":
            continue
        yield {
            "text": node.attrib.get("text", ""),
            "resource_id": node.attrib.get("resource-id", ""),
            "class": node.attrib.get("class", ""),
            "content_desc": node.attrib.get("content-desc", ""),
            "bounds": node.attrib.get("bounds", ""),
        }


def find_nodes(xml_text, text, exact=True):
    matches = []
    for node in iter_nodes(xml_text):
        candidates = [node["text"], node["content_desc"]]
        for candidate in candidates:
            if not candidate:
                continue
            if exact and candidate == text:
                matches.append(node)
                break
            if not exact and text in candidate:
                matches.append(node)
                break
    return matches


def wait_for_text(adb, text, exact=True, timeout=10, interval=0.5):
    start = time.time()
    while time.time() - start < timeout:
        xml_text = adb.dump_ui()
        matches = find_nodes(xml_text, text, exact=exact)
        if matches:
            return matches[0]
        time.sleep(interval)
    return None


def tap_node(adb, node):
    bounds = parse_bounds(node.get("bounds"))
    if not bounds:
        raise AdbError("node has no bounds: {}".format(node))
    x, y = center_of(bounds)
    adb.tap(x, y)


def build_ocr_runtime(settings):
    provider = (settings.ocr.provider or "remote").strip().lower()
    device = (settings.ocr.device or "auto").strip().lower()
    remote_timeout = settings.ocr.timeout or 30
    return {
        "provider": provider,
        "remote_url": settings.ocr.remote_url,
        "remote_timeout": float(remote_timeout),
        "remote_key": settings.ocr.api_key,
        "remote_device": device if provider == "remote" else None,
        "use_gpu": provider == "local" and device in ("gpu", "cuda"),
        "allow_cpu_fallback": True,
    }


def text_matches(candidate, text, exact=True):
    if candidate is None:
        return False
    candidate = str(candidate).strip()
    text = str(text).strip()
    if not text:
        return False
    if exact:
        return candidate == text
    return text in candidate


def sort_ocr_matches(matches):
    def key(item):
        confidence = float(item.get("confidence") or 0)
        bounds = item.get("bounds") or [0, 0, 0, 0]
        return (-confidence, bounds[1], bounds[0])

    return sorted(matches, key=key)


def select_ocr_match(matches, index):
    if not matches:
        return None
    if index is None:
        index = 0
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if index < 0:
        index = len(matches) + index
    if index < 0 or index >= len(matches):
        return None
    return matches[index]


def find_ocr_matches(
    adb,
    text,
    exact,
    ocr_config,
    lang="ch",
    threshold=0.5,
    region=None,
):
    if not ocr_config:
        raise AdbError("OCR is not configured")
    elements, _, _, _, _ = detect_elements(
        adb,
        image_path=None,
        template_dir=None,
        template_threshold=0.85,
        use_ocr=True,
        ocr_lang=lang,
        ocr_threshold=threshold,
        ocr_provider=ocr_config["provider"],
        ocr_remote_url=ocr_config["remote_url"],
        ocr_remote_timeout=ocr_config["remote_timeout"],
        ocr_remote_api_key=ocr_config["remote_key"],
        ocr_remote_device=ocr_config["remote_device"],
        ocr_use_gpu=ocr_config["use_gpu"],
        ocr_allow_cpu_fallback=ocr_config["allow_cpu_fallback"],
        ocr_kwargs=None,
        region=region,
    )
    matches = [
        element
        for element in elements
        if text_matches(element.get("text"), text, exact=exact)
    ]
    return sort_ocr_matches(matches)


def wait_for_ocr_text(
    adb,
    text,
    exact,
    ocr_config,
    lang="ch",
    threshold=0.5,
    region=None,
    timeout=10,
    interval=0.7,
    index=0,
):
    start = time.time()
    while time.time() - start < timeout:
        matches = find_ocr_matches(
            adb,
            text,
            exact,
            ocr_config,
            lang=lang,
            threshold=threshold,
            region=region,
        )
        match = select_ocr_match(matches, index)
        if match:
            return match
        time.sleep(interval)
    return None


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_device_id(adb, device_id):
    if device_id:
        return device_id
    devices = adb.devices()
    if not devices:
        raise AdbError("no adb devices found")
    if len(devices) > 1:
        raise AdbError("multiple devices attached, pass --device")
    return devices[0]


def run_flow(adb, flow_path, ocr_config=None):
    flow = load_json(flow_path)
    steps = flow.get("steps", [])
    if not steps:
        raise AdbError("flow has no steps: {}".format(flow_path))

    for index, step in enumerate(steps, start=1):
        action = step.get("action")
        if not action:
            raise AdbError("step {} missing action".format(index))

        if action in ("wait", "sleep"):
            time.sleep(float(step.get("seconds", 1)))
            continue
        if action == "tap":
            adb.tap(int(step["x"]), int(step["y"]))
            continue
        if action == "swipe":
            adb.swipe(
                int(step["x1"]),
                int(step["y1"]),
                int(step["x2"]),
                int(step["y2"]),
                int(step.get("duration_ms", 300)),
            )
            continue
        if action == "text":
            adb.input_text(step["value"])
            continue
        if action == "keyevent":
            adb.keyevent(int(step["keycode"]))
            continue
        if action == "start_app":
            adb.start_app(step["package"], step.get("activity"))
            continue
        if action == "tap_text":
            exact = bool(step.get("exact", True))
            timeout = float(step.get("timeout", 0))
            if timeout > 0:
                node = wait_for_text(adb, step["text"], exact=exact, timeout=timeout)
            else:
                xml_text = adb.dump_ui()
                nodes = find_nodes(xml_text, step["text"], exact=exact)
                node = nodes[0] if nodes else None
            if not node:
                raise AdbError("tap_text not found: {}".format(step["text"]))
            tap_node(adb, node)
            continue
        if action == "tap_ocr_text":
            exact = bool(step.get("exact", True))
            if step.get("contains"):
                exact = False
            timeout = float(step.get("timeout", 0))
            interval = float(step.get("interval", 0.7))
            threshold = float(step.get("threshold", 0.5))
            lang = step.get("lang", "ch")
            region = step.get("region")
            index = step.get("index", 0)
            if timeout > 0:
                match = wait_for_ocr_text(
                    adb,
                    step["text"],
                    exact=exact,
                    ocr_config=ocr_config,
                    lang=lang,
                    threshold=threshold,
                    region=region,
                    timeout=timeout,
                    interval=interval,
                    index=index,
                )
            else:
                matches = find_ocr_matches(
                    adb,
                    step["text"],
                    exact=exact,
                    ocr_config=ocr_config,
                    lang=lang,
                    threshold=threshold,
                    region=region,
                )
                match = select_ocr_match(matches, index)
            if not match:
                raise AdbError("tap_ocr_text not found: {}".format(step["text"]))
            bounds = match.get("bounds")
            if not bounds:
                raise AdbError("tap_ocr_text missing bounds: {}".format(step["text"]))
            x, y = bounds_center(bounds)
            adb.tap(x, y)
            continue
        if action == "tap_image":
            image_path = step["image"]
            threshold = float(step.get("threshold", 0.85))
            timeout = float(step.get("timeout", 0))
            interval = float(step.get("interval", 0.5))
            region = normalize_region(step.get("region"))
            offset_x, offset_y = parse_offset(step.get("offset"))
            if timeout > 0:
                match = wait_for_image(
                    adb,
                    image_path,
                    threshold=threshold,
                    timeout=timeout,
                    interval=interval,
                    region=region,
                )
            else:
                match = find_image(
                    adb,
                    image_path,
                    threshold=threshold,
                    region=region,
                )
            if not match:
                raise AdbError("tap_image not found: {}".format(image_path))
            x, y = match_center(match)
            adb.tap(x + offset_x, y + offset_y)
            continue
        if action == "wait_text":
            exact = bool(step.get("exact", True))
            timeout = float(step.get("timeout", 10))
            node = wait_for_text(adb, step["text"], exact=exact, timeout=timeout)
            if not node:
                raise AdbError("wait_text timed out: {}".format(step["text"]))
            continue
        if action == "wait_ocr_text":
            exact = bool(step.get("exact", True))
            if step.get("contains"):
                exact = False
            timeout = float(step.get("timeout", 10))
            interval = float(step.get("interval", 0.7))
            threshold = float(step.get("threshold", 0.5))
            lang = step.get("lang", "ch")
            region = step.get("region")
            index = step.get("index", 0)
            match = wait_for_ocr_text(
                adb,
                step["text"],
                exact=exact,
                ocr_config=ocr_config,
                lang=lang,
                threshold=threshold,
                region=region,
                timeout=timeout,
                interval=interval,
                index=index,
            )
            if not match:
                raise AdbError("wait_ocr_text timed out: {}".format(step["text"]))
            continue
        if action == "wait_image":
            image_path = step["image"]
            threshold = float(step.get("threshold", 0.85))
            timeout = float(step.get("timeout", 10))
            interval = float(step.get("interval", 0.5))
            region = normalize_region(step.get("region"))
            match = wait_for_image(
                adb,
                image_path,
                threshold=threshold,
                timeout=timeout,
                interval=interval,
                region=region,
            )
            if not match:
                raise AdbError("wait_image timed out: {}".format(image_path))
            continue
        if action == "screenshot":
            adb.screenshot(step["path"])
            continue
        if action == "dump_ui":
            xml_text = adb.dump_ui()
            Path(step["path"]).write_text(xml_text, encoding="utf-8")
            continue

        raise AdbError("unknown action {} at step {}".format(action, index))


def build_parser():
    parser = argparse.ArgumentParser(description="ADB WeChat automation bot")
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--adb", dest="adb_path", default=None, help="Path to adb")
    parser.add_argument("--device", default=None, help="ADB device id")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("devices", help="List attached devices")

    dump_ui_parser = subparsers.add_parser("dump-ui", help="Dump UI hierarchy to file")
    dump_ui_parser.add_argument("--output", required=True, help="Output xml path")

    list_text = subparsers.add_parser(
        "list-text", help="List nodes with matching text or content-desc"
    )
    list_text.add_argument("--text", required=True, help="Text to match")
    list_text.add_argument("--contains", action="store_true", help="Substring match")

    tap_text_parser = subparsers.add_parser("tap-text", help="Tap a node by text")
    tap_text_parser.add_argument("--text", required=True, help="Text to match")
    tap_text_parser.add_argument("--contains", action="store_true", help="Substring match")
    tap_text_parser.add_argument("--timeout", type=float, default=0, help="Wait timeout")

    list_ocr_text = subparsers.add_parser(
        "list-ocr-text", help="List OCR elements matching text"
    )
    list_ocr_text.add_argument("--text", required=True, help="Text to match")
    list_ocr_text.add_argument("--contains", action="store_true", help="Substring match")
    list_ocr_text.add_argument(
        "--threshold", type=float, default=0.5, help="OCR confidence threshold"
    )
    list_ocr_text.add_argument("--lang", default="ch", help="OCR language (default: ch)")
    list_ocr_text.add_argument(
        "--region",
        default=None,
        help="Crop region for OCR (x1,y1,x2,y2; absolute or 0..1)",
    )
    list_ocr_text.add_argument(
        "--index", type=int, default=None, help="Optional match index"
    )

    tap_ocr_text_parser = subparsers.add_parser(
        "tap-ocr-text", help="Tap an OCR element by text"
    )
    tap_ocr_text_parser.add_argument("--text", required=True, help="Text to match")
    tap_ocr_text_parser.add_argument(
        "--contains", action="store_true", help="Substring match"
    )
    tap_ocr_text_parser.add_argument(
        "--threshold", type=float, default=0.5, help="OCR confidence threshold"
    )
    tap_ocr_text_parser.add_argument(
        "--lang", default="ch", help="OCR language (default: ch)"
    )
    tap_ocr_text_parser.add_argument(
        "--region",
        default=None,
        help="Crop region for OCR (x1,y1,x2,y2; absolute or 0..1)",
    )
    tap_ocr_text_parser.add_argument(
        "--timeout", type=float, default=0, help="Wait timeout"
    )
    tap_ocr_text_parser.add_argument(
        "--interval", type=float, default=0.7, help="Polling interval"
    )
    tap_ocr_text_parser.add_argument(
        "--index", type=int, default=0, help="Match index (default: 0)"
    )

    run_parser = subparsers.add_parser("run", help="Run a flow JSON file")
    run_parser.add_argument("flow", help="Path to flow json")

    screenshot_parser = subparsers.add_parser("screenshot", help="Save screenshot")
    screenshot_parser.add_argument("--output", required=True, help="Output png path")

    find_image_parser = subparsers.add_parser(
        "find-image", help="Find a template image on screen"
    )
    find_image_parser.add_argument("--image", required=True, help="Template image path")
    find_image_parser.add_argument(
        "--threshold", type=float, default=0.85, help="Match threshold"
    )
    find_image_parser.add_argument(
        "--region", default=None, help="Search region x1,y1,x2,y2"
    )

    tap_image_parser = subparsers.add_parser("tap-image", help="Tap a template image")
    tap_image_parser.add_argument("--image", required=True, help="Template image path")
    tap_image_parser.add_argument(
        "--threshold", type=float, default=0.85, help="Match threshold"
    )
    tap_image_parser.add_argument(
        "--timeout", type=float, default=0, help="Wait timeout"
    )
    tap_image_parser.add_argument(
        "--interval", type=float, default=0.5, help="Polling interval"
    )
    tap_image_parser.add_argument(
        "--region", default=None, help="Search region x1,y1,x2,y2"
    )
    tap_image_parser.add_argument(
        "--offset", default=None, help="Tap offset dx,dy"
    )

    cv_detect_parser = subparsers.add_parser(
        "cv-detect", help="Detect UI elements via templates and OCR"
    )
    cv_detect_parser.add_argument(
        "--image", default=None, help="Optional PNG path (defaults to screenshot)"
    )
    cv_detect_parser.add_argument(
        "--templates",
        default="assets/templates",
        help="Template directory (default: assets/templates)",
    )
    cv_detect_parser.add_argument(
        "--template-threshold", type=float, default=0.85, help="Template threshold"
    )
    cv_detect_parser.add_argument(
        "--no-ocr", action="store_true", help="Disable OCR detection"
    )
    cv_detect_parser.add_argument(
        "--ocr-provider",
        choices=["remote", "local"],
        default=None,
        help="OCR provider (default: config or remote)",
    )
    cv_detect_parser.add_argument(
        "--ocr-remote-url",
        default=None,
        help="Remote OCR endpoint (default: config or OCR_REMOTE_URL)",
    )
    cv_detect_parser.add_argument(
        "--ocr-remote-timeout",
        type=float,
        default=None,
        help="Remote OCR timeout seconds (default: config or 30)",
    )
    cv_detect_parser.add_argument(
        "--ocr-remote-key",
        default=None,
        help="Remote OCR API key (X-API-Key header)",
    )
    cv_detect_parser.add_argument(
        "--ocr-remote-device",
        choices=["auto", "gpu", "cpu"],
        default=None,
        help="Remote OCR device override",
    )
    cv_detect_parser.add_argument(
        "--ocr-lang", default="ch", help="OCR language (default: ch)"
    )
    cv_detect_parser.add_argument(
        "--ocr-gpu", action="store_true", help="Use GPU for local OCR"
    )
    cv_detect_parser.add_argument(
        "--ocr-no-fallback",
        action="store_true",
        help="Fail if local GPU OCR is unavailable",
    )
    cv_detect_parser.add_argument(
        "--ocr-threshold", type=float, default=0.5, help="OCR confidence threshold"
    )
    cv_detect_parser.add_argument(
        "--ocr-det-limit-side-len",
        type=int,
        default=None,
        help="OCR det_limit_side_len override",
    )
    cv_detect_parser.add_argument(
        "--ocr-det-db-thresh",
        type=float,
        default=None,
        help="OCR det_db_thresh override",
    )
    cv_detect_parser.add_argument(
        "--ocr-det-db-box-thresh",
        type=float,
        default=None,
        help="OCR det_db_box_thresh override",
    )
    cv_detect_parser.add_argument(
        "--ocr-det-unclip-ratio",
        type=float,
        default=None,
        help="OCR det_db_unclip_ratio override",
    )
    cv_detect_parser.add_argument(
        "--region",
        default=None,
        help="Crop region for detection (x1,y1,x2,y2; absolute or 0..1)",
    )
    cv_detect_parser.add_argument(
        "--output", default=None, help="Write elements JSON to file"
    )
    cv_detect_parser.add_argument(
        "--annotate", default=None, help="Write annotated PNG with element boxes"
    )

    decide_parser = subparsers.add_parser(
        "llm-decide", help="Choose actions from detected elements"
    )
    decide_parser.add_argument("--goal", required=True, help="Goal for the model")
    decide_parser.add_argument(
        "--elements", required=True, help="Path to elements JSON"
    )
    decide_parser.add_argument(
        "--output", default=None, help="Write actions JSON to file"
    )
    decide_parser.add_argument(
        "--execute", action="store_true", help="Execute suggested actions"
    )
    decide_parser.add_argument(
        "--model", default=None, help="OpenAI model (default: gpt-4o-mini)"
    )
    decide_parser.add_argument(
        "--temperature", type=float, default=0.2, help="Model temperature"
    )
    decide_parser.add_argument(
        "--max-actions", type=int, default=5, help="Maximum actions to request"
    )
    decide_parser.add_argument(
        "--max-elements", type=int, default=30, help="Max elements to include"
    )
    decide_parser.add_argument(
        "--api-key", default=None, help="OpenAI API key (or set OPENAI_API_KEY)"
    )

    screen_parser = subparsers.add_parser(
        "screen-info", help="Show screen size and alignment checks"
    )
    screen_parser.add_argument(
        "--no-screenshot", action="store_true", help="Skip screenshot check"
    )

    vision_parser = subparsers.add_parser(
        "vision", help="Use a vision model to suggest UI actions"
    )
    vision_parser.add_argument("--goal", required=True, help="Goal for the model")
    vision_parser.add_argument(
        "--image", default=None, help="Optional PNG path (defaults to screenshot)"
    )
    vision_parser.add_argument(
        "--output", default=None, help="Write actions JSON to file"
    )
    vision_parser.add_argument(
        "--execute", action="store_true", help="Execute suggested actions"
    )
    vision_parser.add_argument(
        "--model", default=None, help="OpenAI model (default: gpt-4o-mini)"
    )
    vision_parser.add_argument(
        "--temperature", type=float, default=0.2, help="Model temperature"
    )
    vision_parser.add_argument(
        "--max-actions", type=int, default=5, help="Maximum actions to request"
    )
    vision_parser.add_argument(
        "--region",
        default=None,
        help="Crop region for vision (x1,y1,x2,y2; absolute or 0..1)",
    )
    vision_parser.add_argument(
        "--api-key", default=None, help="OpenAI API key (or set OPENAI_API_KEY)"
    )
    vision_parser.add_argument(
        "--annotate",
        default=None,
        help="Write annotated PNG with action markers",
    )

    vision_label_parser = subparsers.add_parser(
        "vision-label", help="Use a vision model to label UI elements"
    )
    vision_label_parser.add_argument(
        "--goal", default="Label visible UI elements", help="Context for labeling"
    )
    vision_label_parser.add_argument(
        "--image", default=None, help="Optional PNG path (defaults to screenshot)"
    )
    vision_label_parser.add_argument(
        "--output", default=None, help="Write elements JSON to file"
    )
    vision_label_parser.add_argument(
        "--annotate",
        default="annotated_labels.png",
        help="Write annotated PNG with element boxes",
    )
    vision_label_parser.add_argument(
        "--model", default=None, help="OpenAI model (default: gpt-4o-mini)"
    )
    vision_label_parser.add_argument(
        "--temperature", type=float, default=0.2, help="Model temperature"
    )
    vision_label_parser.add_argument(
        "--max-elements", type=int, default=20, help="Maximum elements to request"
    )
    vision_label_parser.add_argument(
        "--region",
        default=None,
        help="Crop region for vision (x1,y1,x2,y2; absolute or 0..1)",
    )
    vision_label_parser.add_argument(
        "--api-key", default=None, help="OpenAI API key (or set OPENAI_API_KEY)"
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
    except FileNotFoundError as exc:
        raise AdbError(str(exc)) from exc
    adb_path = args.adb_path or settings.adb_path or "adb"
    device_id = args.device or settings.device_id or None

    adb = AdbClient(adb_path=adb_path, device_id=device_id)
    if args.command != "devices":
        needs_device = True
        if args.command in ("vision", "vision-label", "cv-detect") and args.image:
            needs_device = False
        if args.command == "llm-decide" and not args.execute:
            needs_device = False
        if needs_device:
            adb.device_id = resolve_device_id(adb, adb.device_id)

    if args.command == "devices":
        devices = adb.list_devices()
        if not devices:
            print("no adb devices found", file=sys.stderr)
            return 1
        for device_id, status in devices:
            print("{}\t{}".format(device_id, status))
        return 0
    if args.command == "dump-ui":
        xml_text = adb.dump_ui()
        Path(args.output).write_text(xml_text, encoding="utf-8")
        return 0
    if args.command == "list-text":
        xml_text = adb.dump_ui()
        nodes = find_nodes(
            xml_text, args.text, exact=not args.contains
        )
        for node in nodes:
            bounds = parse_bounds(node.get("bounds"))
            print(
                "{} | {} | {}".format(node.get("text") or node.get("content_desc"), bounds, node.get("resource_id"))
            )
        return 0
    if args.command == "tap-text":
        exact = not args.contains
        if args.timeout > 0:
            node = wait_for_text(adb, args.text, exact=exact, timeout=args.timeout)
        else:
            xml_text = adb.dump_ui()
            matches = find_nodes(xml_text, args.text, exact=exact)
            node = matches[0] if matches else None
        if not node:
            raise AdbError("text not found: {}".format(args.text))
        tap_node(adb, node)
        return 0
    if args.command == "list-ocr-text":
        ocr_config = build_ocr_runtime(settings)
        exact = not args.contains
        matches = find_ocr_matches(
            adb,
            args.text,
            exact=exact,
            ocr_config=ocr_config,
            lang=args.lang,
            threshold=args.threshold,
            region=args.region,
        )
        if args.index is not None:
            match = select_ocr_match(matches, args.index)
            matches = [match] if match else []
        for match in matches:
            bounds = match.get("bounds")
            print(
                "{} | {} | {:.3f}".format(
                    match.get("text"),
                    bounds,
                    float(match.get("confidence") or 0),
                )
            )
        return 0
    if args.command == "tap-ocr-text":
        ocr_config = build_ocr_runtime(settings)
        exact = not args.contains
        if args.timeout > 0:
            match = wait_for_ocr_text(
                adb,
                args.text,
                exact=exact,
                ocr_config=ocr_config,
                lang=args.lang,
                threshold=args.threshold,
                region=args.region,
                timeout=args.timeout,
                interval=args.interval,
                index=args.index,
            )
        else:
            matches = find_ocr_matches(
                adb,
                args.text,
                exact=exact,
                ocr_config=ocr_config,
                lang=args.lang,
                threshold=args.threshold,
                region=args.region,
            )
            match = select_ocr_match(matches, args.index)
        if not match:
            raise AdbError("ocr text not found: {}".format(args.text))
        bounds = match.get("bounds")
        if not bounds:
            raise AdbError("ocr match missing bounds: {}".format(args.text))
        x, y = bounds_center(bounds)
        adb.tap(x, y)
        return 0
    if args.command == "find-image":
        region = normalize_region(args.region)
        match = find_image(
            adb,
            args.image,
            threshold=args.threshold,
            region=region,
        )
        if not match:
            print("not found", file=sys.stderr)
            return 1
        center_x, center_y = match_center(match)
        top_left = match["top_left"]
        size = match["size"]
        print(
            "score={:.3f} top_left=({}, {}) center=({}, {}) size=({}, {})".format(
                match["score"],
                top_left[0],
                top_left[1],
                center_x,
                center_y,
                size[0],
                size[1],
            )
        )
        return 0
    if args.command == "tap-image":
        region = normalize_region(args.region)
        offset_x, offset_y = parse_offset(args.offset)
        if args.timeout > 0:
            match = wait_for_image(
                adb,
                args.image,
                threshold=args.threshold,
                timeout=args.timeout,
                interval=args.interval,
                region=region,
            )
        else:
            match = find_image(
                adb,
                args.image,
                threshold=args.threshold,
                region=region,
            )
        if not match:
            raise AdbError("image not found: {}".format(args.image))
        center_x, center_y = match_center(match)
        adb.tap(center_x + offset_x, center_y + offset_y)
        return 0
    if args.command == "cv-detect":
        ocr_provider = args.ocr_provider or settings.ocr.provider or "remote"
        ocr_remote_url = args.ocr_remote_url or settings.ocr.remote_url
        ocr_remote_timeout = args.ocr_remote_timeout
        if ocr_remote_timeout is None:
            ocr_remote_timeout = settings.ocr.timeout or 30
        ocr_remote_timeout = float(ocr_remote_timeout)
        ocr_remote_key = args.ocr_remote_key or settings.ocr.api_key
        ocr_remote_device = args.ocr_remote_device or settings.ocr.device or None

        ocr_kwargs = {}
        if args.ocr_det_limit_side_len:
            ocr_kwargs["det_limit_side_len"] = args.ocr_det_limit_side_len
        if args.ocr_det_db_thresh is not None:
            ocr_kwargs["det_db_thresh"] = args.ocr_det_db_thresh
        if args.ocr_det_db_box_thresh is not None:
            ocr_kwargs["det_db_box_thresh"] = args.ocr_det_db_box_thresh
        if args.ocr_det_unclip_ratio is not None:
            ocr_kwargs["det_db_unclip_ratio"] = args.ocr_det_unclip_ratio
        if not ocr_kwargs:
            ocr_kwargs = None
        elements, width, height, png_bytes, crop_region = detect_elements(
            adb,
            image_path=args.image,
            template_dir=args.templates,
            template_threshold=args.template_threshold,
            use_ocr=not args.no_ocr,
            ocr_lang=args.ocr_lang,
            ocr_threshold=args.ocr_threshold,
            ocr_provider=ocr_provider,
            ocr_remote_url=ocr_remote_url,
            ocr_remote_timeout=ocr_remote_timeout,
            ocr_remote_api_key=ocr_remote_key,
            ocr_remote_device=ocr_remote_device,
            ocr_use_gpu=args.ocr_gpu,
            ocr_allow_cpu_fallback=not args.ocr_no_fallback,
            ocr_kwargs=ocr_kwargs,
            region=args.region,
        )
        output_data = {
            "elements": elements,
            "screen": {"width": width, "height": height},
        }
        if crop_region:
            output_data["region"] = {
                "x1": crop_region[0],
                "y1": crop_region[1],
                "x2": crop_region[2],
                "y2": crop_region[3],
            }
        output_text = json.dumps(output_data, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
        print(output_text)
        if args.annotate:
            annotated = decode_png(png_bytes)
            annotate_elements(annotated, elements, width, height)
            save_image(args.annotate, annotated)
            print("annotated_image={}".format(args.annotate), file=sys.stderr)
        return 0
    if args.command == "llm-decide":
        api_key = args.api_key or settings.openai_api_key
        model = args.model or settings.openai_model or "gpt-4o-mini"
        elements_payload = load_json(args.elements)
        elements = elements_payload.get("elements") or []
        screen = elements_payload.get("screen") or {}
        width = int(screen.get("width", 0)) if screen else 0
        height = int(screen.get("height", 0)) if screen else 0
        if width <= 0 or height <= 0:
            raise AdbError("elements JSON missing screen width/height")
        if elements:
            elements = sorted(
                elements,
                key=lambda item: float(item.get("confidence", 0) or 0),
                reverse=True,
            )
        if args.max_elements and len(elements) > args.max_elements:
            elements = elements[: args.max_elements]
        prompt = build_decision_prompt(args.goal, elements, args.max_actions)
        response_text = call_openai_text(
            api_key,
            model,
            prompt,
            temperature=args.temperature,
        )
        actions = parse_actions_json(response_text)
        if len(actions) > args.max_actions:
            actions = actions[: args.max_actions]
        output_data = {
            "actions": actions,
            "screen": {"width": width, "height": height},
        }
        output_text = json.dumps(output_data, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
        print(output_text)
        if args.execute:
            if not adb.device_id:
                adb.device_id = resolve_device_id(adb, adb.device_id)
            execute_actions(
                adb,
                actions,
                width,
                height,
                log=lambda message: print(message, file=sys.stderr),
                elements=elements,
            )
        return 0
    if args.command == "screen-info":
        size_output = adb.shell(["wm", "size"]).stdout
        density_output = adb.shell(["wm", "density"]).stdout
        wm_size = parse_wm_size(size_output)
        wm_density = parse_wm_density(density_output)
        if wm_size:
            print("wm_size={}x{}".format(wm_size[0], wm_size[1]))
        else:
            print("wm_size=unknown")
        if wm_density:
            print("wm_density={}".format(wm_density))
        else:
            print("wm_density=unknown")
        if args.no_screenshot:
            return 0
        png_bytes = adb.screenshot_bytes()
        shot_width, shot_height = png_size(png_bytes)
        print("screenshot={}x{}".format(shot_width, shot_height))
        if wm_size:
            if (shot_width, shot_height) == wm_size:
                print("alignment=ok")
            elif (shot_width, shot_height) == (wm_size[1], wm_size[0]):
                print("alignment=rotated")
            else:
                print("alignment=mismatch")
        return 0
    if args.command == "vision":
        api_key = args.api_key or settings.openai_api_key
        model = args.model or settings.openai_model or "gpt-4o-mini"
        png_bytes, width, height = get_png_bytes(adb, args.image)
        region = resolve_region(args.region, width, height)
        model_png_bytes = png_bytes
        model_width = width
        model_height = height
        if region:
            full_image = decode_png(png_bytes)
            cropped, _ = crop_image(full_image, region)
            model_png_bytes = encode_png(cropped)
            model_height, model_width = cropped.shape[:2]
        prompt = build_vision_prompt(
            args.goal,
            args.max_actions,
            model_width,
            model_height,
        )
        response_text = call_openai_vision(
            api_key,
            model,
            prompt,
            model_png_bytes,
            temperature=args.temperature,
        )
        actions = parse_actions_json(response_text)
        if len(actions) > args.max_actions:
            actions = actions[: args.max_actions]
        actions = adjust_actions_for_region(actions, region, width, height)
        output_data = {"actions": actions, "screen": {"width": width, "height": height}}
        if region:
            output_data["region"] = {
                "x1": region[0],
                "y1": region[1],
                "x2": region[2],
                "y2": region[3],
            }
        output_text = json.dumps(output_data, indent=2)
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
        print(output_text)
        if args.annotate:
            annotated = decode_png(png_bytes)
            annotate_actions(annotated, actions, width, height)
            save_image(args.annotate, annotated)
            print("annotated_image={}".format(args.annotate), file=sys.stderr)
        if args.execute:
            if not adb.device_id:
                adb.device_id = resolve_device_id(adb, adb.device_id)
            execute_actions(
                adb,
                actions,
                width,
                height,
                log=lambda message: print(message, file=sys.stderr),
            )
        return 0
    if args.command == "vision-label":
        api_key = args.api_key or settings.openai_api_key
        model = args.model or settings.openai_model or "gpt-4o-mini"
        png_bytes, width, height = get_png_bytes(adb, args.image)
        region = resolve_region(args.region, width, height)
        model_png_bytes = png_bytes
        model_width = width
        model_height = height
        if region:
            full_image = decode_png(png_bytes)
            cropped, _ = crop_image(full_image, region)
            model_png_bytes = encode_png(cropped)
            model_height, model_width = cropped.shape[:2]
        prompt = build_vision_label_prompt(
            args.goal,
            args.max_elements,
            model_width,
            model_height,
        )
        response_text = call_openai_vision(
            api_key,
            model,
            prompt,
            model_png_bytes,
            temperature=args.temperature,
        )
        elements = parse_elements_json(response_text)
        if len(elements) > args.max_elements:
            elements = elements[: args.max_elements]
        elements = adjust_elements_for_region(elements, region, width, height)
        elements = elements_to_pixels(elements, width, height)
        output_data = {
            "elements": elements,
            "screen": {"width": width, "height": height},
        }
        if region:
            output_data["region"] = {
                "x1": region[0],
                "y1": region[1],
                "x2": region[2],
                "y2": region[3],
            }
        output_text = json.dumps(output_data, indent=2)
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
        print(output_text)
        if args.annotate:
            annotated = decode_png(png_bytes)
            annotate_elements(annotated, elements, width, height)
            save_image(args.annotate, annotated)
            print("annotated_image={}".format(args.annotate), file=sys.stderr)
        return 0
    if args.command == "run":
        ocr_config = build_ocr_runtime(settings)
        run_flow(adb, args.flow, ocr_config=ocr_config)
        return 0
    if args.command == "screenshot":
        adb.screenshot(args.output)
        return 0

    raise AdbError("unknown command")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AdbError as exc:
        print("error:", exc, file=sys.stderr)
        sys.exit(1)
