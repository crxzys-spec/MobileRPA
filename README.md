# MobileRPA WeChat ADB Bot

This project provides a small Python CLI to automate WeChat UI flows via ADB.
It uses OCR/structure + UIAutomator observations and a vision-capable LLM to
decide next-step actions.

## Requirements
- Python 3.8+
- Android device with USB debugging enabled
- ADB installed and on PATH
- WeChat installed and logged in
- Screen unlocked and on the foreground
- Client deps (remote OCR + LLM): `pip install -r requirements.txt`
- CPU local OCR fallback: `pip install -r requirements-cpu.txt`
- Cloud OCR service: `pip install -r apps/ocr_server/requirements.txt`

## Quick Start
1. Start the OCR service (default endpoint `http://127.0.0.1:8001/ocr`):
   `uvicorn app:app --host 0.0.0.0 --port 8001 --app-dir apps/ocr_server`
2. Connect a device (check with `adb devices`).
3. Run the agent loop:
   `python bot.py agent --goal "Go back" --execute`

## Settings
Client settings load from `.env` (and environment variables). See `.env.example`
for both core agent and MRPA Studio variables. `MRPA_ADB_PATH` is shared.
Set `LLM_TEMPERATURE` to override model temperature, or leave empty to use the
model default (recommended for models that reject non-default temperature).
You can also set `LLM_PROVIDER` plus `LLM_BASE_URL` for OpenAI-compatible
providers such as DeepSeek or Qwen. Legacy `OPENAI_*` variables still act as
fallbacks if `LLM_*` is unset.

## Project Layout
- `bot.py` CLI entrypoint
- `apps/mrpa/` core implementation
- `outputs/` generated artifacts
- `tools/platform-tools/` bundled ADB tools
- `apps/ocr_server/` FastAPI OCR service
- `.env` runtime configuration

## Useful Commands
- Run the agent loop (observe -> decide -> act):
  `python bot.py agent --goal "Go back" --execute --max-steps 3`

## MRPA Studio UI
- Install deps: `pip install -r apps/mrpa_studio/requirements.txt`
- Start the UI: `uvicorn app:app --reload --port 8020 --app-dir apps/mrpa_studio`
- Open `http://127.0.0.1:8020` in your browser
- Live stream uses `adb` + `ffmpeg`. Optional env: `MRPA_STREAM_FPS`, `MRPA_STREAM_SCALE`, `MRPA_STREAM_BITRATE`.
- For 30fps on devices without `screenrecord --output-format`, use scrcpy (auto-detected from `tools/scrcpy`).
- Override stream driver with `MRPA_STREAM_DRIVER=scrcpy|screenrecord|screencap`.

## Cloud OCR Service
The agent uses the cloud OCR service by default. Configure the
endpoint in `.env` via `OCR_REMOTE_URL`.

Start the service:
`uvicorn app:app --host 0.0.0.0 --port 8001 --app-dir apps/ocr_server`

Notes:
- Install deps: `pip install -r apps/ocr_server/requirements.txt`
- For GPU, install `paddlepaddle-gpu` instead of `paddlepaddle`.
- Set `OCR_DEVICE=gpu` on the server to force GPU.
- If `OCR_API_KEY` is set on the server, clients must send `X-API-Key`.
- Copy `.env.example` to `.env` in repo root to configure OCR defaults.
