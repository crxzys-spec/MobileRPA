import argparse
import json
import mimetypes
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ocr_server import app as ocr_app  # noqa: E402


def fetch_image_bytes(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read()
    return Path(source).read_bytes()


def build_multipart(fields, files):
    boundary = "----mrpa-boundary-{}".format(Path().stat().st_mtime_ns)
    lines = []
    for name, value in fields.items():
        lines.append("--{}".format(boundary))
        lines.append('Content-Disposition: form-data; name="{}"'.format(name))
        lines.append("")
        lines.append(str(value))
    for name, filename, data, content_type in files:
        lines.append("--{}".format(boundary))
        lines.append(
            'Content-Disposition: form-data; name="{}"; filename="{}"'.format(
                name, filename
            )
        )
        lines.append("Content-Type: {}".format(content_type))
        lines.append("")
        lines.append(data)
    lines.append("--{}--".format(boundary))
    body = b""
    for item in lines:
        if isinstance(item, bytes):
            body += item + b"\r\n"
        else:
            body += item.encode("utf-8") + b"\r\n"
    return boundary, body


def run_local(args):
    image_bytes = fetch_image_bytes(args.image)
    screen = ocr_app._decode_image(image_bytes)
    ocr = ocr_app._ensure_structure(args.lang, args.device)
    result = ocr_app._run_ocr_sync(ocr, screen)
    elements = ocr_app._parse_ocr_result(
        result, score_threshold=args.threshold, offset=None
    )
    payload = {"elements": elements}
    if args.raw:
        payload["raw_result"] = ocr_app._serialize_raw_result(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("elements={}".format(len(elements)))
        if elements:
            print(json.dumps(elements[:3], ensure_ascii=False, indent=2))


def run_http(args):
    image_bytes = fetch_image_bytes(args.image)
    mime = mimetypes.guess_type(args.image)[0] or "application/octet-stream"
    fields = {"lang": args.lang, "threshold": args.threshold}
    if args.device:
        fields["device"] = args.device
    if args.raw:
        fields["raw"] = "1"
    filename = Path(args.image).name or "image"
    boundary, body = build_multipart(
        fields, [("image", filename, image_bytes, mime)]
    )
    request = urllib.request.Request(args.http, data=body, method="POST")
    request.add_header("Content-Type", "multipart/form-data; boundary={}".format(boundary))
    request.add_header("Content-Length", str(len(body)))
    if args.api_key:
        request.add_header("X-API-Key", args.api_key)
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        text = response.read().decode("utf-8")
    payload = json.loads(text)
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        count = len(elements) if isinstance(elements, list) else 0
        print("elements={}".format(count))
        if isinstance(elements, list) and elements:
            print(json.dumps(elements[:3], ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Test OCR locally or via HTTP")
    parser.add_argument(
        "--image",
        default="https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/general_ocr_002.png",
        help="Image path or URL",
    )
    parser.add_argument("--lang", default="ch", help="OCR language")
    parser.add_argument("--threshold", type=float, default=0.3, help="Score threshold")
    parser.add_argument("--device", default="gpu", help="Device (gpu/cpu/auto)")
    parser.add_argument("--http", default=None, help="HTTP OCR endpoint URL")
    parser.add_argument("--api-key", default=None, help="HTTP X-API-Key")
    parser.add_argument("--timeout", type=float, default=30, help="HTTP timeout")
    parser.add_argument("--raw", action="store_true", help="Include raw OCR result")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.http:
        run_http(args)
    else:
        run_local(args)


if __name__ == "__main__":
    main()
