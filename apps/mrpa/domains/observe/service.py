from typing import Any, Dict, List, Optional, Tuple

from mrpa.contracts import SchemaError, validate_observation_context
from mrpa.domains.ports import DeviceClient, OcrService, UiTreeParser
from mrpa.domains.observe.types import Observation
from mrpa.utils.image_source import get_png_bytes
from shared.errors import AdbError
from shared.utils.png import png_size
from shared.utils.region import resolve_region


def collect_observation(
    adb: DeviceClient,
    image_path: Optional[str] = None,
    region: Any = None,
    include_ocr: bool = True,
    ocr_lang: str = "ch",
    ocr_threshold: float = 0.5,
    ocr_provider: str = "remote",
    ocr_remote_url: Optional[str] = None,
    ocr_remote_timeout: float = 30.0,
    ocr_remote_api_key: Optional[str] = None,
    ocr_remote_device: Optional[str] = None,
    ocr_use_gpu: bool = False,
    ocr_allow_cpu_fallback: bool = True,
    ocr_kwargs: Optional[Dict[str, Any]] = None,
    ocr_raw: bool = True,
    include_ui: bool = True,
    ui_include_xml: bool = False,
    ui_parser: Optional[UiTreeParser] = None,
    ocr_service: Optional[OcrService] = None,
    png_bytes: Optional[bytes] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    ui_view: Optional[Dict[str, Any]] = None,
) -> Observation:
    elements: List[Dict[str, Any]] = []
    ocr_payload: Optional[Dict[str, Any]] = None
    ocr_view: Dict[str, Any] = {"pages": []}
    structure_view: Dict[str, Any] = {"pages": []}
    crop_region = None
    if png_bytes is None:
        png_bytes, width, height = get_png_bytes(adb, image_path)
    else:
        if width is None or height is None:
            width, height = png_size(png_bytes)
    if include_ocr:
        if ocr_service is None:
            raise AdbError("ocr service is required for OCR view")
        if ocr_raw and ocr_provider != "remote":
            raise AdbError("ocr_raw requires the remote OCR provider")
        elements, crop_region, ocr_payload = ocr_service.detect_elements(
            png_bytes=png_bytes,
            width=width,
            height=height,
            region=region,
            ocr_lang=ocr_lang,
            ocr_threshold=ocr_threshold,
            ocr_provider=ocr_provider,
            ocr_remote_url=ocr_remote_url,
            ocr_remote_timeout=ocr_remote_timeout,
            ocr_remote_api_key=ocr_remote_api_key,
            ocr_remote_device=ocr_remote_device,
            ocr_use_gpu=ocr_use_gpu,
            ocr_allow_cpu_fallback=ocr_allow_cpu_fallback,
            ocr_kwargs=ocr_kwargs,
            ocr_raw=bool(ocr_raw and ocr_provider == "remote"),
        )
        if ocr_payload is None:
            ocr_payload = {"elements": elements}
        raw_result = ocr_payload.get("raw_result") if isinstance(ocr_payload, dict) else None
        if ocr_raw and raw_result is None and ocr_provider == "remote":
            raise AdbError("remote OCR did not return raw_result")
        if raw_result is not None:
            ocr_view, structure_view = ocr_service.build_ocr_structure_views(raw_result)
    else:
        crop_region = resolve_region(region, width, height)
    if include_ocr:
        if not ocr_payload:
            ocr_payload = {"elements": elements}

    if include_ui and ui_view is None:
        if ui_parser is None:
            raise AdbError("ui parser is required for UI view")
        try:
            xml_text = adb.dump_ui()
            nodes = []
            for node in ui_parser.iter_nodes(xml_text):
                parsed = dict(node)
                parsed["bounds"] = ui_parser.parse_bounds(node.get("bounds", ""))
                nodes.append(parsed)
            ui_view = {"nodes": nodes}
            if ui_include_xml:
                ui_view["xml"] = xml_text
        except Exception as exc:
            ui_view = {"error": str(exc)}

    observation = Observation(
        png_bytes=png_bytes,
        width=width,
        height=height,
        region=crop_region,
        elements=elements,
        ocr_payload=ocr_payload,
        ocr_view=ocr_view,
        structure_view=structure_view,
        ui_view=ui_view,
    )
    try:
        validate_observation_context(observation.context())
    except SchemaError as exc:
        raise AdbError(str(exc)) from exc
    return observation
