from infra.ocr.types import OcrRequest, OcrResult
from infra.ocr.providers import paddle as paddle_provider
from infra.ocr.providers import remote as remote_provider
from shared.errors import AdbError


_PROVIDERS = {
    "paddle": paddle_provider.run,
    "local": paddle_provider.run,
    "remote": remote_provider.run,
}


def run_ocr(request: OcrRequest) -> OcrResult:
    provider = (request.provider or "remote").lower()
    handler = _PROVIDERS.get(provider)
    if not handler:
        raise AdbError("unknown OCR provider: {}".format(provider))
    return handler(request)
