# MobileRPA WeChat ADB Bot

This project provides a small Python CLI to automate WeChat UI flows via ADB.
It supports both text-based UI matching (uiautomator dump) and image recognition
via template matching.

## Requirements
- Python 3.8+
- Android device with USB debugging enabled
- ADB installed and on PATH
- WeChat installed and logged in
- Screen unlocked and on the foreground
- Client deps (templates + remote OCR): `pip install -r requirements.txt`
- CPU local OCR fallback: `pip install -r requirements-cpu.txt`
- Cloud OCR service: `pip install -r services/ocr_server/requirements.txt`

## Quick Start
1. Start the OCR service (default endpoint `http://127.0.0.1:8001/ocr`):
   `uvicorn app:app --host 0.0.0.0 --port 8001 --app-dir services/ocr_server`
2. Connect a device and verify:
   `python bot.py devices`
3. Run the sample flow:
   `python bot.py run assets/flows/send_message.json --device <DEVICE_ID>`
4. For image recognition flows:
   `python bot.py run assets/flows/send_message_image.json --device <DEVICE_ID>`

## Project Layout
- `bot.py` CLI entrypoint
- `src/mobile_rpa/` core implementation
- `config/config.json` default config
- `assets/flows/` flow definitions
- `assets/templates/` template images
- `outputs/` generated artifacts
- `tools/platform-tools/` bundled ADB tools
- `services/ocr_server/` FastAPI OCR service

## Useful Commands
- Dump UI hierarchy:
  `python bot.py dump-ui --output ui.xml --device <DEVICE_ID>`
- List nodes by text:
  `python bot.py list-text --text Search --contains --device <DEVICE_ID>`
- Tap a node by text:
  `python bot.py tap-text --text Search --contains --device <DEVICE_ID>`
- Take a screenshot:
  `python bot.py screenshot --output screen.png --device <DEVICE_ID>`
- Find a template image:
  `python bot.py find-image --image assets/templates/search.png --device <DEVICE_ID>`
- Tap a template image:
  `python bot.py tap-image --image assets/templates/search.png --device <DEVICE_ID>`
- Detect elements via templates + OCR:
  `python bot.py cv-detect --output elements.json --annotate elements.png`
- Use local OCR instead of cloud:
  `python bot.py cv-detect --ocr-provider local --output elements.json --annotate elements.png`
- Use GPU for local OCR:
  `python bot.py cv-detect --ocr-provider local --ocr-gpu --output elements.json --annotate elements.png`
- Require local GPU (fail if unavailable):
  `python bot.py cv-detect --ocr-provider local --ocr-gpu --ocr-no-fallback --output elements.json --annotate elements.png`
- Tune local OCR sensitivity (helps UI text):
  `python bot.py cv-detect --ocr-provider local --ocr-gpu --ocr-det-limit-side-len 1536 --ocr-det-db-thresh 0.2 --ocr-det-db-box-thresh 0.4 --output elements.json --annotate elements.png`
- Decide actions from elements (LLM):
  `python bot.py llm-decide --goal "打开搜索" --elements elements.json --execute`
- Use a vision model to suggest actions:
  `python bot.py vision --goal "Open search" --execute`
- Focus vision on a region for higher precision:
  `python bot.py vision --goal "Tap send" --region 0,0.7,1,1 --annotate annotated.png`
- Write annotated action markers:
  `python bot.py vision --goal "Tap search" --annotate annotated.png`
- Label UI elements with boxes:
  `python bot.py vision-label --annotate labeled.png`
- Check screen alignment:
  `python bot.py screen-info`

## Image Recognition Mode
If the UI tree is blocked (common on some devices/WeChat pages), use template
matching instead of `tap_text`.

1. Capture a screenshot:
   `python bot.py screenshot --output screen.png`
2. Crop templates (e.g., search icon, send button) using any image tool.
3. Use `tap_image` / `wait_image` actions in your flow.

Example step:
```
{
  "action": "tap_image",
  "image": "assets/templates/search.png",
  "threshold": 0.85,
  "timeout": 5
}
```

Sample image-based flow: `assets/flows/send_message_image.json`

## Vision Model Mode
When templates are hard to maintain, you can ask a vision-capable model to
suggest the next actions from a screenshot.

1. Set your API key:
   `setx OPENAI_API_KEY "<YOUR_KEY>"`
2. Run a goal prompt (captures a screenshot automatically):
   `python bot.py vision --goal "Tap the search icon" --execute`
3. Or provide a saved PNG:
   `python bot.py vision --goal "Open chat list" --image screen.png`

Notes:
- Vision mode sends screenshots to the model API and may incur usage costs.
- Actions are inferred; verify results before running on sensitive screens.
- When `--execute` is used, executed tap/swipe positions are printed to stderr.
- `--annotate` writes a PNG with numbered tap/swipe markers.
- `--region` accepts absolute pixels or normalized 0..1 coordinates.

## Cloud OCR Service
`cv-detect` uses the cloud OCR service by default. Configure the endpoint in
`config/config.json` under `ocr.remote_url` or via `OCR_REMOTE_URL`.

Start the service:
`uvicorn app:app --host 0.0.0.0 --port 8001 --app-dir services/ocr_server`

Notes:
- Install deps: `pip install -r services/ocr_server/requirements.txt`
- For GPU, install `paddlepaddle-gpu` instead of `paddlepaddle`.
- Set `OCR_DEVICE=gpu` on the server to force GPU.
- If `OCR_API_KEY` is set on the server, clients must send `X-API-Key`.
- Clients can set `ocr.api_key` in `config/config.json` or `OCR_API_KEY`.

## CV + LLM Mode (Recommended)
Use machine vision (templates + OCR, cloud default) to locate elements, then let the LLM
choose actions from a structured element list.

1. Install client dependencies:
   `pip install -r requirements.txt`
   CPU fallback:
   - `pip install -r requirements-cpu.txt`
2. Detect elements:
   `python bot.py cv-detect --output elements.json --annotate elements.png`
3. Let the LLM decide actions:
   `python bot.py llm-decide --goal "给张三发消息" --elements elements.json --execute`

Tips:
- Put icon/button templates in `assets/templates/`.
- If OCR is too noisy, raise `--ocr-threshold` or use `--no-ocr`.
- Limit detection to a region for better accuracy: `--region x1,y1,x2,y2`.
- If PaddleOCR stalls on model host checks, set `DISABLE_MODEL_SOURCE_CHECK=True`.
- For local OCR, install `paddlepaddle-gpu` matching your CUDA version and use `--ocr-gpu`.
- If local OCR finds no boxes, lower `--ocr-det-db-thresh`/`--ocr-det-db-box-thresh` or increase `--ocr-det-limit-side-len`.
- If local GPU OCR returns zero boxes, the tool will auto-fallback to CPU unless `--ocr-no-fallback` is set.

## Vision Labeling Mode
To see how the model understands the page, use `vision-label`. It returns
bounding boxes with labels (pixel coordinates) and writes an annotated PNG.

Example:
`python bot.py vision-label --goal "Label all visible UI elements" --annotate labeled.png`

## Flow Format
Flow files are JSON with a `steps` array. Supported actions:
- `start_app` { package, activity? }
- `wait` { seconds }
- `tap` { x, y }
- `swipe` { x1, y1, x2, y2, duration_ms? }
- `text` { value }
- `keyevent` { keycode }
- `tap_text` { text, exact?, timeout? }
- `wait_text` { text, exact?, timeout? }
- `tap_image` { image, threshold?, timeout?, interval?, region?, offset? }
- `wait_image` { image, threshold?, timeout?, interval?, region? }
- `screenshot` { path }
- `dump_ui` { path }

See `assets/flows/send_message.json` for an example. You will likely need to update
text labels and coordinates to match your WeChat UI language and screen size.
