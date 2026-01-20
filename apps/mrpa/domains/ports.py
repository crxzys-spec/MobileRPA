from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple, Union


class DeviceClient(Protocol):
    def tap(self, x: int, y: int) -> None:
        ...

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> None:
        ...

    def keyevent(self, keycode: Union[int, str]) -> None:
        ...

    def input_text(self, text: str) -> None:
        ...

    def screenshot_bytes(self) -> bytes:
        ...

    def dump_ui(self) -> str:
        ...


class UiTreeParser(Protocol):
    def iter_nodes(self, xml_text: str) -> Iterable[Dict[str, str]]:
        ...

    def parse_bounds(self, bounds: str) -> Optional[Tuple[int, int, int, int]]:
        ...


class OcrService(Protocol):
    def detect_elements(
        self,
        *,
        png_bytes: bytes,
        width: int,
        height: int,
        region: Any,
        ocr_lang: str,
        ocr_threshold: float,
        ocr_provider: str,
        ocr_remote_url: Optional[str],
        ocr_remote_timeout: float,
        ocr_remote_api_key: Optional[str],
        ocr_remote_device: Optional[str],
        ocr_use_gpu: bool,
        ocr_allow_cpu_fallback: bool,
        ocr_kwargs: Optional[Dict[str, Any]],
        ocr_raw: bool,
    ) -> Tuple[
        List[Dict[str, Any]],
        Optional[Tuple[int, int, int, int]],
        Optional[Dict[str, Any]],
    ]:
        ...

    def build_ocr_structure_views(
        self, raw_result: Any
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        ...
