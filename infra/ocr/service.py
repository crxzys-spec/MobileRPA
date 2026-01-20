from infra.ocr.templates import (
    find_image,
    match_center,
    wait_for_image,
)
from infra.ocr.strategy import detect_elements
from infra.ocr.views import build_ocr_structure_views


class OcrServiceAdapter:
    def detect_elements(
        self,
        *,
        png_bytes,
        width,
        height,
        region,
        ocr_lang,
        ocr_threshold,
        ocr_provider,
        ocr_remote_url,
        ocr_remote_timeout,
        ocr_remote_api_key,
        ocr_remote_device,
        ocr_use_gpu,
        ocr_allow_cpu_fallback,
        ocr_kwargs,
        ocr_raw,
    ):
        return detect_elements(
            png_bytes=png_bytes,
            width=width,
            height=height,
            template_dir=None,
            template_threshold=0.0,
            use_ocr=True,
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
            region=region,
            ocr_remote_raw=ocr_raw,
            ocr_return_payload=ocr_raw,
        )

    def build_ocr_structure_views(self, raw_result):
        return build_ocr_structure_views(raw_result)


__all__ = [
    "detect_elements",
    "find_image",
    "match_center",
    "wait_for_image",
    "build_ocr_structure_views",
    "OcrServiceAdapter",
]
