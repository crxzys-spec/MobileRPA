from typing import Any, Dict, List, Optional, Tuple

from infra.ocr.router import run_ocr
from infra.ocr.templates import (
    collect_template_paths,
    match_template,
)
from infra.ocr.types import OcrRequest
from shared.errors import AdbError
from shared.utils.geometry import bounds_center
from infra.image.image import decode_png, load_image
from shared.utils.region import crop_image, resolve_region


def _offset_bounds(bounds: List[int], offset: Optional[Tuple[int, int]]):
    if not offset:
        return bounds
    dx, dy = offset
    return [bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy]


def _offset_elements(elements: List[Dict[str, Any]], offset: Optional[Tuple[int, int]]):
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


def _unique_id(base: str, used: set):
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
        bounds = _offset_bounds(bounds, offset)
        element_id = _unique_id("tpl:{}".format(template_path.stem), used_ids)
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


def detect_elements(
    png_bytes,
    width,
    height,
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
    ocr_remote_raw=False,
    ocr_return_payload=False,
):
    screen = decode_png(png_bytes)
    crop_region = resolve_region(region, width, height)
    cropped = screen
    offset = None
    if crop_region:
        cropped, offset = crop_image(screen, crop_region)
    elements = []
    elements.extend(detect_templates(cropped, template_dir, template_threshold, offset))
    if ocr_remote_raw and not use_ocr:
        raise AdbError("--ocr-raw/--annotate-structure requires OCR enabled")
    if ocr_remote_raw and ocr_provider != "remote":
        raise AdbError("--ocr-raw/--annotate-structure requires the remote OCR provider")
    ocr_payload = None
    if use_ocr:
        request = OcrRequest(
            image=cropped,
            lang=ocr_lang,
            threshold=ocr_threshold,
            provider=ocr_provider,
            use_gpu=ocr_use_gpu,
            allow_cpu_fallback=ocr_allow_cpu_fallback,
            ocr_kwargs=ocr_kwargs,
            remote_url=ocr_remote_url,
            remote_timeout=ocr_remote_timeout,
            remote_api_key=ocr_remote_api_key,
            remote_device=ocr_remote_device,
            raw=bool(ocr_remote_raw and ocr_provider == "remote"),
            annotate=False,
        )
        result = run_ocr(request)
        ocr_elements = _offset_elements(result.elements or [], offset)
        elements.extend(ocr_elements)
        want_payload = bool(ocr_return_payload or ocr_remote_raw)
        if want_payload:
            if result.payload is None:
                ocr_payload = {"elements": ocr_elements}
            else:
                ocr_payload = result.payload
                if isinstance(ocr_payload, dict):
                    ocr_payload["elements"] = ocr_elements
            if ocr_remote_raw and ocr_provider == "remote":
                if not isinstance(ocr_payload, dict) or "raw_result" not in ocr_payload:
                    raise AdbError("remote OCR did not return raw_result")
    return elements, crop_region, ocr_payload
