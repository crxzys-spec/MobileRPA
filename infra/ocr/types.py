from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class OcrRequest:
    image: Any
    lang: str
    threshold: float
    provider: str
    use_gpu: bool
    allow_cpu_fallback: bool
    ocr_kwargs: Optional[Dict[str, Any]]
    remote_url: Optional[str]
    remote_timeout: float
    remote_api_key: Optional[str]
    remote_device: Optional[str]
    raw: bool
    annotate: bool


@dataclass
class OcrResult:
    elements: List[Dict[str, Any]]
    payload: Optional[Dict[str, Any]]
