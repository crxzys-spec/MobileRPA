import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from infra.image.diff import compare_png_bytes
from infra.llm import LlmConfig
from infra.ocr import OcrServiceAdapter
from infra.uiautomator import DEFAULT_PARSER
from mrpa.contracts import Decision, SchemaError, actions_to_dicts, validate_actions
from mrpa.domains.act import execute_actions
from mrpa.domains.decide import DecisionRequest, decide_actions
from mrpa.domains.observe import collect_observation
from mrpa.domains.observe.types import Observation
from mrpa.domains.plan import (
    MemoryStore,
    PlanManager,
    SkillLibrary,
    choose_skill,
    execute_skill,
    summarize_observation,
    verify_plan_step,
)
from mrpa.settings import ClientSettings, build_llm_config, resolve_ocr_runtime
from mrpa.utils import (
    build_page_hint,
    get_png_bytes,
    resize_png_bytes,
    ui_nodes_to_elements,
    ui_view_has_valid_nodes,
)
from shared.errors import AdbError


@dataclass
class AgentConfig:
    max_actions: int = 5
    max_steps: int = 1
    include_images: bool = True
    include_ui: bool = True
    include_ocr: bool = True
    ocr_raw: bool = True
    ocr_lang: str = "ch"
    ocr_threshold: float = 0.5
    model: Optional[str] = None
    temperature: Optional[float] = None
    decision_mode: str = "vision_ocr"
    trace_dir: Optional[str] = None
    plan_enabled: bool = False
    plan_max_steps: int = 5
    plan_resume: bool = True
    plan_verify_mode: str = "llm"
    use_skills: bool = False
    skills_only: bool = False
    skills_dir: Optional[str] = None
    memory_path: Optional[str] = None
    memory_max_entries: int = 200
    memory_enabled: Optional[bool] = None
    verify_actions: bool = False
    verify_change_ratio: float = 0.001
    verify_pixel_threshold: int = 10
    verify_delay: float = 0.4
    max_retries: int = 0
    retry_delay: float = 0.4
    fallback_decision_mode: Optional[str] = "auto"
    stop_if_text: Optional[List[str]] = None
    stop_if_mode: str = "contains"
    stop_if_source: str = "elements"
    plan_image_max_side: int = 720


@dataclass
class AttemptResult:
    attempt: int
    observation: Observation
    decision: Decision
    prompt: str
    response_text: str
    decision_mode: str
    post_png_bytes: Optional[bytes] = None
    verification: Optional[Dict[str, object]] = None
    stop_reason: Optional[str] = None
    skill: Optional[Dict[str, object]] = None
    skill_error: Optional[str] = None
    plan_verify: Optional[Dict[str, object]] = None

    def summary(self) -> Dict[str, object]:
        payload = {
            "attempt": self.attempt,
            "decision_mode": self.decision_mode,
            "actions": actions_to_dicts(self.decision.actions),
            "done": self.decision.done,
        }
        if self.decision.done_reason is not None:
            payload["done_reason"] = self.decision.done_reason
        if self.verification is not None:
            payload["verification"] = dict(self.verification)
        if self.stop_reason:
            payload["stop_reason"] = self.stop_reason
        if self.skill is not None:
            payload["skill"] = dict(self.skill)
        if self.skill_error:
            payload["skill_error"] = self.skill_error
        if self.plan_verify is not None:
            payload["plan_verify"] = dict(self.plan_verify)
        return payload


@dataclass
class AgentStepResult:
    step: int
    observation: Observation
    decision: Decision
    prompt: str
    response_text: str
    decision_mode: str
    post_png_bytes: Optional[bytes] = None
    verification: Optional[Dict[str, object]] = None
    attempts: Optional[List[AttemptResult]] = None
    stop_reason: Optional[str] = None
    goal: Optional[str] = None
    plan: Optional[Dict[str, object]] = None
    skill: Optional[Dict[str, object]] = None
    skill_error: Optional[str] = None
    plan_verify: Optional[Dict[str, object]] = None

    def to_dict(self) -> dict:
        payload = {
            "step": self.step,
            "screen": {
                "width": self.observation.width,
                "height": self.observation.height,
            },
            "actions": actions_to_dicts(self.decision.actions),
            "decision_mode": self.decision_mode,
            "done": self.decision.done,
            "context": self.observation.context(),
        }
        if self.goal:
            payload["goal"] = self.goal
        if self.plan is not None:
            payload["plan"] = dict(self.plan)
        if self.skill is not None:
            payload["skill"] = dict(self.skill)
        if self.skill_error:
            payload["skill_error"] = self.skill_error
        if self.plan_verify is not None:
            payload["plan_verify"] = dict(self.plan_verify)
        if self.decision.done_reason is not None:
            payload["done_reason"] = self.decision.done_reason
        if self.verification is not None:
            payload["verification"] = dict(self.verification)
        if self.attempts and len(self.attempts) > 1:
            payload["attempts"] = [attempt.summary() for attempt in self.attempts]
        if self.stop_reason:
            payload["stop_reason"] = self.stop_reason
        return payload


class AgentRuntime:
    def __init__(
        self,
        adb,
        settings: ClientSettings,
        config: Optional[AgentConfig] = None,
        llm_config: Optional[LlmConfig] = None,
    ):
        self.adb = adb
        self.settings = settings
        self.config = config or AgentConfig()
        if not self.config.plan_image_max_side or self.config.plan_image_max_side <= 0:
            self.config.plan_image_max_side = settings.plan_image_max_side
        self.llm_config = llm_config
        self.memory = self._init_memory()
        self.skills = self._init_skills()
        self.plan_manager = self._init_plan_manager()

    def _init_memory(self) -> Optional[MemoryStore]:
        enabled = self.config.memory_enabled
        if enabled is None:
            enabled = bool(
                self.config.plan_enabled
                or self.config.use_skills
                or self.config.memory_path
            )
        if not enabled:
            return None
        memory_path = self.config.memory_path or "outputs/memory.json"
        store = MemoryStore(
            path=Path(memory_path),
            max_entries=int(self.config.memory_max_entries or 0),
        )
        store.load()
        return store

    def _init_skills(self) -> Optional[SkillLibrary]:
        if not self.config.use_skills:
            return None
        skills_dir = self.config.skills_dir or "skills"
        library = SkillLibrary.load_from_dir(skills_dir)
        return library

    def _init_plan_manager(self) -> Optional[PlanManager]:
        if not self.config.plan_enabled:
            return None
        return PlanManager(
            max_steps=int(self.config.plan_max_steps or 1),
            resume=bool(self.config.plan_resume),
            memory=self.memory,
            skills=self.skills,
        )

    def _verify_plan_step(
        self,
        goal: str,
        observation: Observation,
        *,
        use_vision: bool = True,
        png_bytes: Optional[bytes] = None,
    ) -> Optional[Dict[str, object]]:
        if not self.plan_manager:
            return None
        mode = (self.config.plan_verify_mode or "none").strip().lower()
        if mode == "none":
            return None
        llm_config = self._resolve_llm_config() if mode == "llm" else None
        memory_entries = self.memory.tail(5) if self.memory else None
        if use_vision and png_bytes is None:
            png_bytes = observation.png_bytes
        result = verify_plan_step(
            goal,
            observation,
            llm_config=llm_config,
            mode=mode,
            png_bytes=png_bytes if use_vision else None,
            memory_entries=memory_entries,
        )
        return result.to_dict()

    def _resolve_llm_config(self) -> LlmConfig:
        if self.llm_config:
            return self.llm_config
        return build_llm_config(
            self.settings,
            model=self.config.model,
            api_key=self.llm_config.api_key if self.llm_config else None,
            temperature=self.config.temperature,
        )

    def _resolve_fallback_mode(self, current_mode: str) -> str:
        mode = (self.config.fallback_decision_mode or "").strip().lower()
        if not mode or mode == "same":
            return current_mode
        return mode

    def _check_stop(self, observation: Observation) -> Optional[str]:
        patterns = self.config.stop_if_text or []
        if not patterns:
            return None
        mode = (self.config.stop_if_mode or "contains").strip().lower()
        source = (self.config.stop_if_source or "elements").strip().lower()
        candidates: List[str] = []
        if source in ("elements", "both"):
            for element in observation.elements or []:
                text = element.get("text")
                if text:
                    candidates.append(str(text).strip())
        if source in ("ui", "both"):
            ui_view = observation.ui_view
            if isinstance(ui_view, dict):
                nodes = ui_view.get("nodes") or []
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    for key in ("text", "content_desc"):
                        text = node.get(key)
                        if text:
                            candidates.append(str(text).strip())
        if not candidates:
            return None
        for raw_pattern in patterns:
            if raw_pattern is None:
                continue
            pattern = str(raw_pattern).strip()
            if not pattern:
                continue
            for candidate in candidates:
                if not candidate:
                    continue
                if mode == "exact":
                    if candidate == pattern:
                        return "text_match:{}".format(pattern)
                else:
                    if pattern in candidate:
                        return "text_match:{}".format(pattern)
        return None

    def _run_attempt(
        self,
        attempt_index: int,
        goal: str,
        *,
        image_path: Optional[str],
        region: Optional[object],
        execute: bool,
        text_only: bool,
        decision_mode: str,
        should_verify: bool,
    ) -> AttemptResult:
        ocr_runtime = resolve_ocr_runtime(self.settings)
        effective_decision_mode = decision_mode
        effective_text_only = text_only
        include_ui = bool(self.config.include_ui)
        include_ocr = bool(self.config.include_ocr)
        png_bytes = None
        width = None
        height = None
        if include_ui and include_ocr:
            png_bytes, width, height = get_png_bytes(self.adb, image_path)
            observation = collect_observation(
                self.adb,
                image_path=image_path,
                region=region,
                include_ocr=False,
                ocr_lang=self.config.ocr_lang,
                ocr_threshold=self.config.ocr_threshold,
                ocr_provider=ocr_runtime.provider,
                ocr_remote_url=ocr_runtime.remote_url,
                ocr_remote_timeout=ocr_runtime.timeout,
                ocr_remote_api_key=ocr_runtime.api_key,
                ocr_remote_device=ocr_runtime.remote_device,
                ocr_use_gpu=ocr_runtime.use_gpu,
                ocr_allow_cpu_fallback=True,
                ocr_kwargs=None,
                ocr_raw=self.config.ocr_raw,
                include_ui=include_ui,
                ui_parser=DEFAULT_PARSER if include_ui else None,
                ocr_service=OcrServiceAdapter() if include_ocr else None,
                png_bytes=png_bytes,
                width=width,
                height=height,
            )
            if ui_view_has_valid_nodes(observation.ui_view):
                observation.elements = ui_nodes_to_elements(observation.ui_view)
                effective_decision_mode = "elements"
                effective_text_only = True
            else:
                observation = collect_observation(
                    self.adb,
                    image_path=image_path,
                    region=region,
                    include_ocr=include_ocr,
                    ocr_lang=self.config.ocr_lang,
                    ocr_threshold=self.config.ocr_threshold,
                    ocr_provider=ocr_runtime.provider,
                    ocr_remote_url=ocr_runtime.remote_url,
                    ocr_remote_timeout=ocr_runtime.timeout,
                    ocr_remote_api_key=ocr_runtime.api_key,
                    ocr_remote_device=ocr_runtime.remote_device,
                    ocr_use_gpu=ocr_runtime.use_gpu,
                    ocr_allow_cpu_fallback=True,
                    ocr_kwargs=None,
                    ocr_raw=self.config.ocr_raw,
                    include_ui=include_ui,
                    ui_parser=DEFAULT_PARSER if include_ui else None,
                    ocr_service=OcrServiceAdapter() if include_ocr else None,
                    png_bytes=png_bytes,
                    width=width,
                    height=height,
                    ui_view=observation.ui_view,
                )
                effective_decision_mode = "vision"
        else:
            observation = collect_observation(
                self.adb,
                image_path=image_path,
                region=region,
                include_ocr=include_ocr,
                ocr_lang=self.config.ocr_lang,
                ocr_threshold=self.config.ocr_threshold,
                ocr_provider=ocr_runtime.provider,
                ocr_remote_url=ocr_runtime.remote_url,
                ocr_remote_timeout=ocr_runtime.timeout,
                ocr_remote_api_key=ocr_runtime.api_key,
                ocr_remote_device=ocr_runtime.remote_device,
                ocr_use_gpu=ocr_runtime.use_gpu,
                ocr_allow_cpu_fallback=True,
                ocr_kwargs=None,
                ocr_raw=self.config.ocr_raw,
                include_ui=include_ui,
                ui_parser=DEFAULT_PARSER if include_ui else None,
                ocr_service=OcrServiceAdapter() if include_ocr else None,
            )
            if include_ui:
                if ui_view_has_valid_nodes(observation.ui_view):
                    observation.elements = ui_nodes_to_elements(observation.ui_view)
                    effective_decision_mode = "elements"
                    effective_text_only = True
                else:
                    effective_decision_mode = "vision"
        stop_reason = self._check_stop(observation)
        if stop_reason:
            return AttemptResult(
                attempt=attempt_index,
                observation=observation,
                decision=Decision(actions=[]),
                prompt="",
                response_text="",
                decision_mode="stop",
                stop_reason=stop_reason,
            )

        plan_verify_bytes = None
        use_plan_verify_vision = self.config.include_images and not effective_text_only
        if use_plan_verify_vision:
            plan_verify_bytes = resize_png_bytes(
                observation.png_bytes, max_side=self.config.plan_image_max_side
            )
        plan_verify = self._verify_plan_step(
            goal,
            observation,
            use_vision=use_plan_verify_vision,
            png_bytes=plan_verify_bytes,
        )
        plan_verified_done = bool(plan_verify and plan_verify.get("done"))
        if plan_verified_done:
            return AttemptResult(
                attempt=attempt_index,
                observation=observation,
                decision=Decision(actions=[], done=True),
                prompt="",
                response_text="",
                decision_mode="plan_verify",
                plan_verify=plan_verify,
            )

        llm_config = self._resolve_llm_config()
        skill_payload = None
        skill_error = None
        decision = None
        resolved_mode = None
        prompt = ""
        response_text = ""
        if self.config.use_skills:
            if not self.skills or not self.skills.skills:
                skill_error = "skills enabled but no skills loaded"
                if self.config.skills_only:
                    decision = Decision(actions=[])
                    resolved_mode = "skills"
            else:
                try:
                    memory_entries = self.memory.tail(5) if self.memory else None
                    skill_decision = choose_skill(
                        goal,
                        observation,
                        self.skills,
                        llm_config,
                        memory_entries=memory_entries,
                    )
                    selection = skill_decision.selection
                    skill_payload = selection.to_dict()
                    prompt = skill_decision.prompt
                    response_text = skill_decision.response_text
                    resolved_mode = "skills"
                    selection_done = bool(selection.done and plan_verified_done)
                    if selection.done and not plan_verified_done:
                        selection_done = False
                    if selection_done:
                        decision = Decision(
                            actions=[],
                            raw_text=selection.raw_text,
                            done=True,
                            done_reason=selection.done_reason,
                        )
                    elif selection.name:
                        skill_result = execute_skill(
                            selection.name,
                            selection.params,
                            observation,
                            self.skills,
                        )
                        if skill_result.error:
                            skill_error = skill_result.error
                        if skill_result.actions:
                            try:
                                validate_actions(skill_result.actions)
                            except SchemaError as exc:
                                skill_error = str(exc)
                                if self.config.skills_only:
                                    decision = Decision(actions=[])
                            else:
                                decision = Decision(
                                    actions=skill_result.actions,
                                    raw_text=selection.raw_text,
                                )
                        else:
                            if skill_error is None:
                                skill_error = "skill produced no actions"
                            if self.config.skills_only:
                                decision = Decision(actions=[])
                    elif self.config.skills_only:
                        decision = Decision(actions=[])
                except AdbError as exc:
                    skill_error = str(exc)
                    if self.config.skills_only:
                        decision = Decision(actions=[])
                        resolved_mode = "skills"

        if decision is None:
            images: List[bytes] = []
            image_labels: List[str] = []
            if self.config.include_images and not effective_text_only:
                images.append(observation.png_bytes)
                image_labels.append("screenshot")

            decision_response = decide_actions(
                DecisionRequest(
                    goal=goal,
                    observation=observation,
                    max_actions=self.config.max_actions,
                    image_labels=image_labels,
                    images=images,
                    decision_mode=effective_decision_mode,
                    text_only=effective_text_only,
                ),
                llm_config,
            )
            decision = decision_response.decision
            if plan_verify and not plan_verified_done and decision.done:
                decision.done = False
                decision.done_reason = None
            resolved_mode = decision_response.decision_mode
            prompt = decision_response.prompt
            response_text = decision_response.response_text

        post_png_bytes = None
        verification = None
        if execute and decision.actions:
            action_dicts = actions_to_dicts(decision.actions)
            execute_actions(
                self.adb,
                action_dicts,
                observation.width,
                observation.height,
                elements=observation.elements,
            )
            needs_post = should_verify or self.config.trace_dir
            if needs_post:
                if self.config.verify_delay:
                    time.sleep(self.config.verify_delay)
                post_png_bytes = self.adb.screenshot_bytes()
            if post_png_bytes and should_verify:
                verification = compare_png_bytes(
                    observation.png_bytes,
                    post_png_bytes,
                    pixel_threshold=self.config.verify_pixel_threshold,
                )
                changed_ratio = float(verification.get("changed_ratio", 0.0))
                size_changed = bool(verification.get("size_changed"))
                verification["changed"] = bool(
                    size_changed or changed_ratio >= self.config.verify_change_ratio
                )
                verification["threshold"] = self.config.verify_change_ratio
                verification["pixel_threshold"] = self.config.verify_pixel_threshold

        return AttemptResult(
            attempt=attempt_index,
            observation=observation,
            decision=decision,
            prompt=prompt,
            response_text=response_text,
            decision_mode=resolved_mode or effective_decision_mode,
            post_png_bytes=post_png_bytes,
            verification=verification,
            skill=skill_payload,
            skill_error=skill_error,
            plan_verify=plan_verify,
        )

    def step(
        self,
        goal: str,
        *,
        image_path: Optional[str] = None,
        region: Optional[object] = None,
        execute: bool = False,
        text_only: bool = False,
    ) -> AgentStepResult:
        max_retries = int(self.config.max_retries or 0)
        if max_retries < 0:
            max_retries = 0
        retry_delay = float(self.config.retry_delay or 0)
        if retry_delay < 0:
            retry_delay = 0.0
        should_verify = self.config.verify_actions or max_retries > 0
        requested_mode = self.config.decision_mode
        fallback_mode = self._resolve_fallback_mode(requested_mode)
        attempts: List[AttemptResult] = []
        attempt_index = 1
        current_image_path = image_path
        max_attempts = max_retries + 1
        while True:
            if attempt_index > 1 and retry_delay:
                time.sleep(retry_delay)
            attempt = self._run_attempt(
                attempt_index,
                goal,
                image_path=current_image_path,
                region=region,
                execute=execute,
                text_only=text_only,
                decision_mode=requested_mode,
                should_verify=should_verify,
            )
            attempts.append(attempt)
            if attempt.stop_reason:
                break
            if attempt.decision.done:
                break
            if not execute or not attempt.decision.actions:
                break
            if not should_verify or not attempt.verification:
                break
            if attempt.verification.get("changed"):
                break
            if attempt_index >= max_attempts:
                break
            requested_mode = fallback_mode
            current_image_path = None
            attempt_index += 1

        final_attempt = attempts[-1]
        return AgentStepResult(
            step=1,
            observation=final_attempt.observation,
            decision=final_attempt.decision,
            prompt=final_attempt.prompt,
            response_text=final_attempt.response_text,
            decision_mode=final_attempt.decision_mode,
            post_png_bytes=final_attempt.post_png_bytes,
            verification=final_attempt.verification,
            attempts=attempts,
            stop_reason=final_attempt.stop_reason,
            skill=final_attempt.skill,
            skill_error=final_attempt.skill_error,
            plan_verify=final_attempt.plan_verify,
        )

    def _write_attempt_trace(
        self, attempt: AttemptResult, goal: str, target_dir: Path
    ) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "screen.png").write_bytes(attempt.observation.png_bytes)
        (target_dir / "context.json").write_text(
            json.dumps(attempt.observation.context(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target_dir / "decision.json").write_text(
            json.dumps(
                {
                    "goal": goal,
                    "attempt": attempt.attempt,
                    "decision_mode": attempt.decision_mode,
                    "page_hint": build_page_hint(
                        attempt.observation.elements,
                        attempt.observation.height,
                        ocr_payload=attempt.observation.ocr_payload,
                        ui_view=attempt.observation.ui_view,
                    ),
                    "actions": actions_to_dicts(attempt.decision.actions),
                    "done": attempt.decision.done,
                    "done_reason": attempt.decision.done_reason,
                    "stop_reason": attempt.stop_reason,
                    "skill": attempt.skill,
                    "skill_error": attempt.skill_error,
                    "plan_verify": attempt.plan_verify,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (target_dir / "prompt.txt").write_text(attempt.prompt, encoding="utf-8")
        (target_dir / "response.txt").write_text(attempt.response_text, encoding="utf-8")
        if attempt.observation.ocr_payload is not None:
            (target_dir / "ocr_payload.json").write_text(
                json.dumps(
                    attempt.observation.ocr_payload, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
        if attempt.post_png_bytes:
            (target_dir / "screen_after.png").write_bytes(attempt.post_png_bytes)
        if attempt.verification is not None:
            (target_dir / "verification.json").write_text(
                json.dumps(attempt.verification, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _write_trace(self, result: AgentStepResult, goal: str, trace_dir: Path) -> None:
        step_dir = trace_dir / "step_{:02d}".format(result.step)
        attempts = result.attempts or []
        if attempts:
            self._write_attempt_trace(attempts[-1], goal, step_dir)
            if len(attempts) > 1:
                for attempt in attempts:
                    attempt_dir = step_dir / "attempt_{:02d}".format(attempt.attempt)
                    self._write_attempt_trace(attempt, goal, attempt_dir)
            return
        fallback_attempt = AttemptResult(
            attempt=1,
            observation=result.observation,
            decision=result.decision,
            prompt=result.prompt,
            response_text=result.response_text,
            decision_mode=result.decision_mode,
            post_png_bytes=result.post_png_bytes,
            verification=result.verification,
        )
        self._write_attempt_trace(fallback_attempt, goal, step_dir)

    def _store_memory(self, result: AgentStepResult, root_goal: str, step_goal: str) -> None:
        if not self.memory:
            return
        entry = {
            "timestamp": time.time(),
            "root_goal": root_goal,
            "goal": step_goal,
            "step": result.step,
            "decision_mode": result.decision_mode,
            "actions": actions_to_dicts(result.decision.actions),
            "done": result.decision.done,
            "done_reason": result.decision.done_reason,
            "stop_reason": result.stop_reason,
            "skill": result.skill,
            "skill_error": result.skill_error,
            "plan_verify": result.plan_verify,
            "observation": summarize_observation(result.observation),
        }
        if result.verification is not None:
            entry["verification"] = dict(result.verification)
        if self.plan_manager and self.plan_manager.state:
            entry["plan"] = self.plan_manager.state.to_dict()
        self.memory.append_entry(entry)

    def run(
        self,
        goal: str,
        *,
        image_path: Optional[str] = None,
        region: Optional[object] = None,
        execute: bool = False,
        text_only: bool = False,
        max_steps: Optional[int] = None,
    ) -> List[AgentStepResult]:
        steps: List[AgentStepResult] = []
        limit = max_steps or self.config.max_steps
        trace_dir = Path(self.config.trace_dir) if self.config.trace_dir else None
        root_goal = goal
        step_goal = goal
        use_plan_vision = bool(self.config.include_images and not text_only)
        plan_png_bytes = None
        if self.plan_manager:
            if use_plan_vision:
                try:
                    plan_png_bytes, _, _ = get_png_bytes(self.adb, image_path)
                except Exception as exc:
                    raise AdbError(str(exc)) from exc
                plan_png_bytes = resize_png_bytes(
                    plan_png_bytes, max_side=self.config.plan_image_max_side
                )
            self.plan_manager.ensure_plan(
                goal,
                self._resolve_llm_config(),
                png_bytes=plan_png_bytes,
            )
            step_goal = self.plan_manager.current_goal(goal)
        for index in range(1, limit + 1):
            result = self.step(
                step_goal,
                image_path=image_path,
                region=region,
                execute=execute,
                text_only=text_only,
            )
            result.step = index
            result.goal = step_goal
            plan_done = None
            if self.plan_manager:
                if result.plan_verify is not None:
                    plan_done = bool(result.plan_verify.get("done"))
                else:
                    plan_done = result.decision.done
                if plan_done:
                    self.plan_manager.mark_done()
            if self.plan_manager:
                result.plan = self.plan_manager.to_dict()
            steps.append(result)
            if trace_dir:
                self._write_trace(result, step_goal, trace_dir)
            self._store_memory(result, root_goal, step_goal)
            if not execute:
                break
            if result.stop_reason:
                break
            if self.plan_manager:
                if plan_done:
                    if self.plan_manager.is_done():
                        break
                    self.plan_manager.replan(
                        root_goal,
                        self._resolve_llm_config(),
                        png_bytes=resize_png_bytes(
                            result.observation.png_bytes,
                            max_side=self.config.plan_image_max_side,
                        )
                        if use_plan_vision
                        else None,
                    )
                    step_goal = self.plan_manager.current_goal(root_goal)
                    continue
                if not result.decision.actions:
                    break
            else:
                if result.decision.done or not result.decision.actions:
                    break
        return steps
