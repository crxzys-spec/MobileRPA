import argparse
import json
import sys
from pathlib import Path

from infra.adb import AdbClient
from mrpa.agent import AgentConfig, AgentRuntime
from shared.errors import AdbError
from mrpa.settings import build_llm_config, load_settings


def resolve_device_id(adb, device_id):
    if device_id:
        return device_id
    devices = adb.devices()
    if not devices:
        raise AdbError("no adb devices found")
    if len(devices) > 1:
        raise AdbError("multiple devices attached, pass --device")
    return devices[0]


def build_parser():
    parser = argparse.ArgumentParser(description="ADB WeChat automation bot")
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--adb", dest="adb_path", default=None, help="Path to adb")
    parser.add_argument("--device", default=None, help="ADB device id")

    subparsers = parser.add_subparsers(dest="command", required=True)

    agent_parser = subparsers.add_parser(
        "agent",
        help="Run the agent loop (observe -> decide -> act)",
    )
    agent_parser.add_argument("--goal", required=True, help="Goal for the agent")
    agent_parser.add_argument(
        "--image", default=None, help="Optional PNG path (defaults to screenshot)"
    )
    agent_parser.add_argument(
        "--output", default=None, help="Write agent result JSON to file"
    )
    agent_parser.add_argument(
        "--execute", action="store_true", help="Execute suggested actions"
    )
    agent_parser.add_argument(
        "--max-steps", type=int, default=1, help="Maximum agent steps"
    )
    agent_parser.add_argument(
        "--max-actions", type=int, default=5, help="Maximum actions per step"
    )
    agent_parser.add_argument(
        "--text-only",
        action="store_true",
        help="Send only OCR/structure text to the model (no images)",
    )
    agent_parser.add_argument(
        "--decision-mode",
        choices=("vision_ocr", "elements", "vision", "auto"),
        default=None,
        help="Decision prompt strategy (default: vision_ocr)",
    )
    agent_parser.add_argument(
        "--skills",
        action="store_true",
        help="Enable skill selection before action planning",
    )
    agent_parser.add_argument(
        "--skills-only",
        action="store_true",
        help="Do not fallback to action planning when no skill matches",
    )
    agent_parser.add_argument(
        "--skills-dir",
        default=None,
        help="Directory containing skill JSON files (default: skills)",
    )
    agent_parser.add_argument(
        "--no-ui", action="store_true", help="Disable UIAutomator view"
    )
    agent_parser.add_argument(
        "--no-ocr", action="store_true", help="Disable OCR/structure view"
    )
    agent_parser.add_argument(
        "--region",
        default=None,
        help="Crop region for observation (x1,y1,x2,y2; absolute or 0..1)",
    )
    agent_parser.add_argument(
        "--model", default=None, help="LLM model (default: config)"
    )
    agent_parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Model temperature (default: env or model default)",
    )
    agent_parser.add_argument(
        "--api-key", default=None, help="LLM API key (or set LLM_API_KEY/OPENAI_API_KEY)"
    )
    agent_parser.add_argument(
        "--trace-dir",
        default=None,
        help="Write per-step traces (screenshots, prompts, decisions) to a directory",
    )
    agent_parser.add_argument(
        "--plan",
        action="store_true",
        help="Enable goal decomposition into sub-steps",
    )
    agent_parser.add_argument(
        "--plan-max-steps",
        type=int,
        default=5,
        help="Maximum number of plan steps (default: 5)",
    )
    agent_parser.add_argument(
        "--plan-image-max-side",
        type=int,
        default=None,
        help="Max side (pixels) for plan/verify screenshots (default: env/config)",
    )
    agent_parser.add_argument(
        "--plan-resume",
        dest="plan_resume",
        action="store_true",
        default=True,
        help="Resume the last plan from memory (default: true)",
    )
    agent_parser.add_argument(
        "--no-plan-resume",
        dest="plan_resume",
        action="store_false",
        help="Do not resume plans from memory",
    )
    agent_parser.add_argument(
        "--plan-verify",
        choices=("none", "llm"),
        default="llm",
        help="Plan step verification mode (default: llm)",
    )
    agent_parser.add_argument(
        "--memory-path",
        default=None,
        help="Path to memory JSON (default: outputs/memory.json when enabled)",
    )
    agent_parser.add_argument(
        "--memory-max-entries",
        type=int,
        default=200,
        help="Maximum memory entries to keep (default: 200)",
    )
    agent_parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable memory persistence",
    )
    agent_parser.add_argument(
        "--verify-actions",
        action="store_true",
        help="Verify screen changes after executing actions",
    )
    agent_parser.add_argument(
        "--verify-change",
        type=float,
        default=0.001,
        help="Minimum changed-pixel ratio to mark a change (default: 0.001)",
    )
    agent_parser.add_argument(
        "--verify-pixel-threshold",
        type=int,
        default=10,
        help="Pixel diff threshold for change detection (default: 10)",
    )
    agent_parser.add_argument(
        "--verify-delay",
        type=float,
        default=0.4,
        help="Seconds to wait before verification screenshot (default: 0.4)",
    )
    agent_parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Retry when no screen change is detected (default: 0)",
    )
    agent_parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.4,
        help="Seconds to wait before retrying (default: 0.4)",
    )
    agent_parser.add_argument(
        "--fallback-decision-mode",
        choices=("vision_ocr", "elements", "vision", "auto", "same"),
        default="auto",
        help="Decision mode to use on retries (default: auto)",
    )
    agent_parser.add_argument(
        "--stop-if-text",
        action="append",
        default=None,
        help="Stop if OCR/UI text matches (repeatable)",
    )
    agent_parser.add_argument(
        "--stop-if-mode",
        choices=("contains", "exact"),
        default="contains",
        help="Text match mode for stop conditions (default: contains)",
    )
    agent_parser.add_argument(
        "--stop-if-source",
        choices=("elements", "ui", "both"),
        default="elements",
        help="Text source for stop conditions (default: elements)",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
    except FileNotFoundError as exc:
        raise AdbError(str(exc)) from exc
    adb_path = args.adb_path or settings.adb_path or "adb"
    device_id = args.device or settings.device_id or None

    adb = AdbClient(
        adb_path=adb_path,
        device_id=device_id,
        ime_id=settings.adb_ime_id,
        restore_ime=settings.adb_ime_restore,
    )
    needs_device = True
    if args.command == "agent":
        if not args.execute and args.image and args.no_ui and args.no_ocr:
            needs_device = False
    if needs_device:
        adb.device_id = resolve_device_id(adb, adb.device_id)

    if args.command == "agent":
        use_skills = bool(args.skills or args.skills_only)
        memory_enabled = None
        if args.no_memory:
            memory_enabled = False
        config = AgentConfig(
            max_actions=args.max_actions,
            max_steps=args.max_steps,
            include_images=not args.text_only,
            include_ui=not args.no_ui,
            include_ocr=not args.no_ocr,
            model=args.model,
            temperature=args.temperature,
            decision_mode=args.decision_mode or "vision_ocr",
            trace_dir=args.trace_dir,
            plan_enabled=args.plan,
            plan_max_steps=args.plan_max_steps,
            plan_resume=args.plan_resume,
            plan_verify_mode=args.plan_verify,
            plan_image_max_side=(
                args.plan_image_max_side
                if args.plan_image_max_side is not None
                else settings.plan_image_max_side
            ),
            use_skills=use_skills,
            skills_only=args.skills_only,
            skills_dir=args.skills_dir,
            memory_path=args.memory_path,
            memory_max_entries=args.memory_max_entries,
            memory_enabled=memory_enabled,
            verify_actions=args.verify_actions,
            verify_change_ratio=args.verify_change,
            verify_pixel_threshold=args.verify_pixel_threshold,
            verify_delay=args.verify_delay,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            fallback_decision_mode=args.fallback_decision_mode,
            stop_if_text=args.stop_if_text,
            stop_if_mode=args.stop_if_mode,
            stop_if_source=args.stop_if_source,
        )
        runtime = AgentRuntime(adb, settings, config)
        steps = runtime.run(
            args.goal,
            image_path=args.image,
            region=args.region,
            execute=args.execute,
            text_only=args.text_only,
            max_steps=args.max_steps,
        )
        output_data = {"steps": [step.to_dict() for step in steps]}
        output_text = json.dumps(output_data, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
        print(output_text)
        return 0

    raise AdbError("unknown command")
