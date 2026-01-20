import inspect
import os
import sys
from typing import Any, Dict, Optional

from shared.errors import AdbError
from infra.ocr.parsing import parse_ocr_result
from infra.ocr.types import OcrRequest, OcrResult


os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
_OCR_CACHE: Dict[str, Any] = {}


def ensure_paddleocr(
    lang: str = "ch",
    use_gpu: bool = False,
    allow_cpu_fallback: bool = True,
    extra_kwargs: Optional[Dict[str, Any]] = None,
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

        def allow_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
            if accepts_kwargs:
                return kwargs
            return {key: value for key, value in kwargs.items() if key in params}

        base_kwargs: Dict[str, Any] = {"lang": lang}
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

        last_error: Optional[Exception] = None
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


def run(request: OcrRequest) -> OcrResult:
    ocr = ensure_paddleocr(
        lang=request.lang,
        use_gpu=request.use_gpu,
        allow_cpu_fallback=request.allow_cpu_fallback,
        extra_kwargs=request.ocr_kwargs,
    )
    try:
        result = run_ocr(ocr, request.image)
    except NotImplementedError as exc:
        raise AdbError(
            "PaddleOCR backend failed. Check your paddlepaddle install and "
            "verify GPU/CPU compatibility."
        ) from exc
    elements = parse_ocr_result(result, score_threshold=request.threshold)
    payload = {"raw_result": result} if request.raw else None
    if request.use_gpu and request.allow_cpu_fallback and not elements:
        ocr_cpu = ensure_paddleocr(
            lang=request.lang,
            use_gpu=False,
            allow_cpu_fallback=True,
            extra_kwargs=request.ocr_kwargs,
        )
        result_cpu = run_ocr(ocr_cpu, request.image)
        elements_cpu = parse_ocr_result(result_cpu, score_threshold=request.threshold)
        if elements_cpu:
            print("warning: GPU OCR returned 0 boxes; fell back to CPU", file=sys.stderr)
            elements = elements_cpu
            if request.raw:
                payload = {"raw_result": result_cpu}
    return OcrResult(elements=elements, payload=payload)
