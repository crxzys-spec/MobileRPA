import json

import re

from dataclasses import dataclass

from typing import Any, Dict, List, Optional



from infra.llm import LlmConfig, call_llm_text, call_llm_vision

from infra.llm.errors import LlmError

from mrpa.domains.plan.memory import MemoryStore, summarize_observation

from mrpa.domains.plan.skills import SkillLibrary

from mrpa.domains.plan.types import (

    PlanState,

    PlanStep,

    PlanVerifyResult,

    SkillSelection,

)

from shared.errors import AdbError





@dataclass

class SkillDecision:

    selection: SkillSelection

    prompt: str

    response_text: str





def _extract_json(text: str) -> str:

    cleaned = text.strip()

    if cleaned.startswith("```"):

        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()

        cleaned = re.sub(r"```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)

    if not match:

        raise AdbError("model response did not include JSON")

    return match.group(0)





_PLAN_CONNECTORS = [
    "并且",
    "然后",
    "随后",
    "之后",
    "以后",
    "并",
    "以及",
    "同时",
    " and ",
    " then ",
]




def _split_outside_quotes(text: str, separators: List[str]) -> List[str]:
    if not text or not separators:
        return [text]
    parts: List[str] = []
    buffer: List[str] = []
    index = 0
    in_quote: Optional[str] = None
    separators_sorted = sorted(separators, key=len, reverse=True)
    while index < len(text):
        ch = text[index]
        if in_quote:
            buffer.append(ch)
            if in_quote == ch:
                in_quote = None
            elif in_quote == "“" and ch == "”":
                in_quote = None
            elif in_quote == "‘" and ch == "’":
                in_quote = None
            index += 1
            continue
        if ch in ("'", '"', "“", "‘"):
            in_quote = ch
            buffer.append(ch)
            index += 1
            continue
        matched = None
        for sep in separators_sorted:
            if text.startswith(sep, index):
                matched = sep
                break
        if matched:
            part = "".join(buffer).strip()
            parts.append(part)
            buffer = []
            index += len(matched)
            continue
        buffer.append(ch)
        index += 1
    if buffer:
        parts.append("".join(buffer).strip())
    return parts


def _clean_segment(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = re.sub(r"^[,，。！？、\s]+", "", cleaned)
    cleaned = re.sub(r"[,，。！？、\s]+$", "", cleaned)
    for prefix in ("并且", "然后", "随后", "之后", "以后", "并", "以及", "同时"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned



def _split_compound_goal(goal: str) -> List[str]:

    if not goal:

        return [goal]

    parts = _split_outside_quotes(goal, _PLAN_CONNECTORS)

    cleaned = [_clean_segment(item) for item in parts]

    cleaned = [item for item in cleaned if item and len(item) >= 2]

    if len(cleaned) < 2:

        return [goal.strip()]

    return cleaned





def _normalize_plan_steps(steps: List[PlanStep], max_steps: int) -> List[PlanStep]:

    normalized: List[PlanStep] = []

    for step in steps:

        segments = _split_compound_goal(step.goal)

        for index, segment in enumerate(segments):

            note = step.note if index == 0 else None

            normalized.append(PlanStep(goal=segment, note=note, status="pending"))

            if max_steps and len(normalized) >= max_steps:

                return normalized

    return normalized or steps





def _normalize_text(value: Any) -> str:

    if value is None:

        return ""

    return str(value).strip().lower()





def _collect_text_items(observation, source: str = "both") -> List[Dict[str, Any]]:

    mode = (source or "both").strip().lower()

    items: List[Dict[str, Any]] = []

    if mode in ("elements", "both"):

        for element in observation.elements or []:

            text = element.get("text")

            if text:

                items.append(

                    {

                        "text": str(text),

                        "bounds": element.get("bounds"),

                        "source": "elements",

                    }

                )

    if mode in ("ui", "both"):

        ui_view = observation.ui_view

        if isinstance(ui_view, dict):

            for node in ui_view.get("nodes") or []:

                if not isinstance(node, dict):

                    continue

                for key in ("text", "content_desc"):

                    value = node.get(key)

                    if value:

                        items.append(

                            {

                                "text": str(value),

                                "bounds": node.get("bounds"),

                                "source": "ui",

                            }

                        )

    return items





def _extract_quoted(text: str) -> List[str]:

    if not text:

        return []

    items = re.findall(r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]", text)

    cleaned = []

    seen = set()

    for item in items:

        value = item.strip()

        if not value:

            continue

        if value in seen:

            continue

        seen.add(value)

        cleaned.append(value)

    return cleaned





def _strip_goal_noise(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\"'“”‘’]", " ", text)
    cleaned = re.sub(r"[，。！？、：.!?;:()（）]", " ", cleaned)
    return cleaned


def _extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    cleaned = _strip_goal_noise(text)
    tokens: List[str] = []
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{2,}", cleaned))
    tokens.extend(re.findall(r"[A-Za-z0-9_]{2,}", cleaned))
    suffixes = ("页面", "界面", "按钮", "输入框", "搜索框", "入口", "选项", "列表")
    expanded: List[str] = []
    for token in tokens:
        expanded.append(token)
        for suffix in suffixes:
            if token.endswith(suffix) and len(token) > len(suffix):
                base = token[: -len(suffix)]
                if len(base) >= 2:
                    expanded.append(base)
    stopwords = {
        "点击",
        "进入",
        "打开",
        "输入",
        "发送",
        "返回",
        "选择",
        "切换",
        "等待",
        "查看",
        "完成",
        "确认",
        "取消",
    }
    keywords: List[str] = []
    seen = set()
    for token in expanded:
        value = token.strip()
        if not value or value in stopwords:
            continue
        if value in seen:
            continue
        seen.add(value)
        keywords.append(value)
    return keywords


def _goal_is_page_navigation(goal: str) -> bool:
    if not goal:
        return False
    verbs = ("打开", "进入", "切换", "回到", "返回", "前往", "去到")
    blockers = ("按钮", "搜索框", "输入框", "输入", "图标", "icon", "弹窗", "对话框")
    for verb in verbs:
        if verb in goal:
            target = goal.split(verb, 1)[-1].strip()
            if not target:
                continue
            for blocker in blockers:
                if blocker in target:
                    return False
            return True
    return False



def _is_bottom_nav(bounds: Any, height: int, ratio: float = 0.85) -> bool:

    if not bounds or height <= 0:

        return False

    try:

        y1 = float(bounds[1])

    except (TypeError, ValueError, IndexError):

        return False

    return y1 >= height * ratio





def _heuristic_verify(goal: str, observation, source: str = "both") -> PlanVerifyResult:

    quoted = _extract_quoted(goal)

    keywords = [item for item in _extract_keywords(goal) if item not in quoted]

    items = _collect_text_items(observation, source=source)

    is_page = _goal_is_page_navigation(goal)

    height = getattr(observation, "height", 0) or 0

    filtered_items: List[Dict[str, Any]] = []

    for item in items:

        bounds = item.get("bounds")

        if is_page:

            if bounds is None:

                continue

            if _is_bottom_nav(bounds, height):

                continue

        filtered_items.append(item)

    normalized = [_normalize_text(item.get("text")) for item in filtered_items]



    def _has_match(keyword: str) -> bool:

        key = _normalize_text(keyword)

        if not key:

            return False

        for candidate in normalized:

            if key in candidate:

                return True

        return False



    evidence: List[str] = []

    required = quoted or keywords

    if not required:

        return PlanVerifyResult(done=False, mode="heuristic", evidence=[])

    for item in required:

        if _has_match(item):

            evidence.append(item)

    done = False

    if quoted:

        done = len(evidence) == len(quoted)

        if done and keywords:

            context_match = any(_has_match(item) for item in keywords)

            if not context_match:

                done = False

    else:

        done = len(evidence) > 0

    return PlanVerifyResult(done=done, mode="heuristic", evidence=evidence)





def build_plan_verify_prompt(

    goal: str,

    observation_summary: Dict[str, Any],

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> str:

    memory_text = ""

    if memory_entries:

        memory_text = (

            "Recent memory (JSON):\n"

            + json.dumps(memory_entries, ensure_ascii=False)

            + "\n"

        )

    return (

        "You are a UI state verifier. Decide whether the sub-goal is already achieved.\n"

        "Return JSON only with this schema:\n"

        "{{\n"

        '  "done": false,\n'

        '  "evidence": ["short text evidence"],\n'

        '  "reason": "optional"\n'

        "}}\n"

        "Constraints:\n"

        "- Only say done=true if the evidence is clearly visible.\n"

        "- Use the screenshot if provided; only cite visible evidence.\n"

        "- If unsure, set done=false.\n"

        "Sub-goal: {goal}\n"

        "Observation summary (JSON):\n"

        "{summary}\n"

        "{memory_text}"

    ).format(

        goal=goal,

        summary=json.dumps(observation_summary, ensure_ascii=False),

        memory_text=memory_text,

    )





def parse_plan_verify_text(text: str) -> PlanVerifyResult:

    payload = json.loads(_extract_json(text))

    done = bool(payload.get("done"))

    evidence = payload.get("evidence") or []

    if not isinstance(evidence, list):

        evidence = []

    reason = payload.get("reason") or payload.get("done_reason")

    return PlanVerifyResult(

        done=done,

        mode="llm",

        evidence=[str(item) for item in evidence if item is not None],

        reason=reason,

        response_text=text,

    )





def verify_plan_step(

    goal: str,

    observation,

    *,

    llm_config: Optional[LlmConfig],

    mode: str = "llm",

    png_bytes: Optional[bytes] = None,

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> PlanVerifyResult:

    mode_value = (mode or "none").strip().lower()

    if mode_value == "none":

        return PlanVerifyResult(done=False, mode="none", evidence=[])

    if mode_value != "llm":

        return PlanVerifyResult(done=False, mode=mode_value, evidence=[])

    if llm_config is None:

        return PlanVerifyResult(

            done=False,

            mode="llm",

            evidence=[],

            error="missing llm config",

        )

    summary = summarize_observation(observation)

    prompt = build_plan_verify_prompt(goal, summary, memory_entries=memory_entries)

    try:

        if png_bytes is not None:

            response_text = call_llm_vision(llm_config, prompt, png_bytes)

        else:

            response_text = call_llm_text(llm_config, prompt)

    except LlmError as exc:

        return PlanVerifyResult(

            done=False,

            mode="llm_error",

            evidence=[],

            error=str(exc),

        )

    try:

        result = parse_plan_verify_text(response_text)

    except Exception as exc:

        return PlanVerifyResult(

            done=False,

            mode="llm_error",

            evidence=[],

            error=str(exc),

            response_text=response_text,

        )

    result.prompt = prompt

    return result



def build_plan_prompt(

    goal: str,

    max_steps: int,

    skills: Optional[SkillLibrary] = None,

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> str:

    skills_text = ""

    if skills and skills.skills:

        skills_text = (

            "Available skills (JSON):\n"

            + json.dumps(skills.list_for_prompt(), ensure_ascii=False)

            + "\n"

        )

    memory_text = ""

    if memory_entries:

        memory_text = (

            "Recent memory (JSON):\n"

            + json.dumps(memory_entries, ensure_ascii=False)

            + "\n"

        )

    return (

        "You are a task planner for Android UI automation. "

        "Break the goal into short, actionable sub-goals.\n"

        "Return JSON only with this schema:\n"

        "{{\n"

        '  "steps": [\n'

        '    {{"goal": "...", "note": "optional"}}\n'

        "  ]\n"

        "}}\n"

        "Constraints:\n"

        "- Provide at most {max_steps} steps.\n"

        "- Each goal is a short, atomic sentence.\n"

        "- Each goal must be directly verifiable from a single screenshot.\n"

        "- Use the screenshot if provided to align steps with the current UI.\n"

        "- Use memory if provided to avoid repeating completed steps.\n"

        "- Avoid provenance or preconditions (e.g., 'from the home screen').\n"

        "- Avoid compound steps (no 'and/then' or multiple actions).\n"

        "- If the goal is already atomic, return a single step.\n"

        "Goal: {goal}\n"

        "{skills_text}"

        "{memory_text}"

    ).format(

        max_steps=max_steps,

        goal=goal,

        skills_text=skills_text,

        memory_text=memory_text,

    )





def parse_plan_text(text: str, max_steps: int) -> List[PlanStep]:

    payload = json.loads(_extract_json(text))

    steps_data = payload.get("steps")

    if not isinstance(steps_data, list):

        raise AdbError("plan JSON missing steps list")

    steps: List[PlanStep] = []

    for item in steps_data:

        if not isinstance(item, dict):

            continue

        goal = str(item.get("goal") or "").strip()

        if not goal:

            continue

        note = item.get("note")

        steps.append(PlanStep(goal=goal, note=note, status="pending"))

        if max_steps and len(steps) >= max_steps:

            break

    if not steps:

        raise AdbError("plan did not include any steps")

    return steps





def generate_plan(

    goal: str,

    max_steps: int,

    llm_config: LlmConfig,

    png_bytes: Optional[bytes] = None,

    skills: Optional[SkillLibrary] = None,

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> PlanState:

    if max_steps <= 1:

        plan = PlanState(goal=goal, steps=[PlanStep(goal=goal, status="pending")])

        plan._sync_statuses()

        return plan

    prompt = build_plan_prompt(goal, max_steps, skills=skills, memory_entries=memory_entries)

    try:

        if png_bytes is not None:

            response_text = call_llm_vision(llm_config, prompt, png_bytes)

        else:

            response_text = call_llm_text(llm_config, prompt)

    except LlmError as exc:

        raise AdbError(str(exc)) from exc

    try:

        steps = parse_plan_text(response_text, max_steps=max_steps)

    except AdbError:

        steps = [PlanStep(goal=goal, status="pending")]

    plan = PlanState(goal=goal, steps=steps, current_index=0)

    plan._sync_statuses()

    return plan





def build_skill_prompt(

    goal: str,

    observation_summary: Dict[str, Any],

    skills: SkillLibrary,

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> str:

    memory_text = ""

    if memory_entries:

        memory_text = (

            "Recent memory (JSON):\n"

            + json.dumps(memory_entries, ensure_ascii=False)

            + "\n"

        )

    return (

        "You are a skill selector for Android UI automation. "

        "Pick the best single skill and parameters for the next step.\n"

        "Return JSON only with this schema:\n"

        "{{\n"

        '  "done": false,\n'

        '  "skill": "skill_name or null",\n'

        '  "params": {{}},\n'

        '  "reason": "optional"\n'

        "}}\n"

        "Constraints:\n"

        "- skill must be one of the available skills or null.\n"

        "- If the goal is achieved, set done=true and skill=null.\n"

        "- If unsure, set skill=null.\n"

        "- Only choose input_text when input_focus_hint.focused is true.\n"

        "- If text is needed and input_focus_hint.focused is false, choose tap_text to focus the field\n"

        "  or use input_text with target_text to tap the field first.\n"

        "Goal: {goal}\n"

        "Available skills (JSON):\n"

        "{skills}\n"

        "Observation summary (JSON):\n"

        "{summary}\n"

        "{memory_text}"

    ).format(

        goal=goal,

        skills=json.dumps(skills.list_for_prompt(), ensure_ascii=False),

        summary=json.dumps(observation_summary, ensure_ascii=False),

        memory_text=memory_text,

    )





def parse_skill_text(text: str, skills: SkillLibrary) -> SkillSelection:

    payload = json.loads(_extract_json(text))

    done = bool(payload.get("done"))

    skill_name = payload.get("skill")

    if skill_name is None:

        skill_name = payload.get("name")

    if skill_name is not None:

        skill_name = str(skill_name).strip()

        if not skill_name:

            skill_name = None

    params = payload.get("params") or {}

    if not isinstance(params, dict):

        params = {}

    done_reason = payload.get("done_reason") or payload.get("doneReason")

    selection = SkillSelection(

        name=skill_name,

        params=params,

        done=done,

        done_reason=done_reason,

        raw_text=text,

    )

    if selection.name and not skills.get(selection.name):

        selection.name = None

    return selection





def choose_skill(

    goal: str,

    observation,

    skills: SkillLibrary,

    llm_config: LlmConfig,

    memory_entries: Optional[List[Dict[str, Any]]] = None,

) -> SkillDecision:

    summary = summarize_observation(observation)

    prompt = build_skill_prompt(goal, summary, skills, memory_entries=memory_entries)

    try:

        response_text = call_llm_text(llm_config, prompt)

    except LlmError as exc:

        raise AdbError(str(exc)) from exc

    selection = parse_skill_text(response_text, skills)

    return SkillDecision(selection=selection, prompt=prompt, response_text=response_text)





class PlanManager:

    def __init__(

        self,

        *,

        max_steps: int = 5,

        resume: bool = True,

        memory: Optional[MemoryStore] = None,

        skills: Optional[SkillLibrary] = None,

    ):

        self.max_steps = max_steps

        self.resume = resume

        self.memory = memory

        self.skills = skills

        self.state: Optional[PlanState] = None



    def ensure_plan(

        self,

        goal: str,

        llm_config: LlmConfig,

        png_bytes: Optional[bytes] = None,

    ) -> PlanState:

        if self.state and self.state.goal == goal:

            return self.state

        if self.resume and self.memory and self.memory.plan:

            if self.memory.plan.goal == goal and not self.memory.plan.is_done():

                self.state = self.memory.plan

                return self.state

        memory_entries = self.memory.tail(3) if self.memory else None

        self.state = generate_plan(

            goal,

            max_steps=self.max_steps,

            llm_config=llm_config,

            png_bytes=png_bytes,

            skills=self.skills,

            memory_entries=memory_entries,

        )

        if self.memory:

            self.memory.update_plan(self.state)

        return self.state



    def replan(

        self,

        goal: str,

        llm_config: LlmConfig,

        png_bytes: Optional[bytes] = None,

    ) -> PlanState:

        memory_entries = self.memory.tail(3) if self.memory else None

        self.state = generate_plan(

            goal,

            max_steps=self.max_steps,

            llm_config=llm_config,

            png_bytes=png_bytes,

            skills=self.skills,

            memory_entries=memory_entries,

        )

        if self.memory:

            self.memory.update_plan(self.state)

        return self.state



    def current_goal(self, fallback_goal: str) -> str:

        if not self.state:

            return fallback_goal

        step = self.state.current_step()

        if step and step.goal:

            return step.goal

        return fallback_goal



    def mark_done(self) -> None:

        if not self.state:

            return

        self.state.advance()

        if self.memory:

            self.memory.update_plan(self.state)



    def is_done(self) -> bool:

        return bool(self.state and self.state.is_done())



    def to_dict(self) -> Optional[Dict[str, Any]]:

        if not self.state:

            return None

        return self.state.to_dict()

