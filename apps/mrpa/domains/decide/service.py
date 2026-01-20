from infra.llm import LlmConfig, call_llm_text, call_llm_vision_multi
from infra.llm.errors import LlmError
from mrpa.contracts import (
    Decision,
    SchemaError,
    parse_decision_text,
    validate_actions,
    validate_actions_for_mode,
)
from mrpa.domains.decide.prompts.elements import build_decision_prompt
from mrpa.domains.decide.prompts.vision import build_vision_prompt
from mrpa.domains.decide.prompts.vision_ocr import build_vision_ocr_prompt
from mrpa.domains.decide.types import DecisionRequest, DecisionResponse
from mrpa.utils import build_page_hint, detect_input_focus
from shared.errors import AdbError


def _resolve_decision_mode(mode: str) -> str:
    if not mode:
        return "vision_ocr"
    return str(mode).strip().lower()


def decide_actions(request: DecisionRequest, llm_config: LlmConfig) -> DecisionResponse:
    observation = request.observation
    input_focus_hint = detect_input_focus(
        observation.elements,
        observation.height,
        ocr_payload=observation.ocr_payload,
        ui_view=observation.ui_view,
    )
    page_hint = build_page_hint(
        observation.elements,
        observation.height,
        ocr_payload=observation.ocr_payload,
        ui_view=observation.ui_view,
    )
    decision_mode = _resolve_decision_mode(request.decision_mode)
    if decision_mode == "auto":
        decision_mode = "elements" if observation.elements else "vision_ocr"

    if decision_mode == "elements":
        prompt = build_decision_prompt(
            request.goal,
            observation.elements,
            request.max_actions,
            input_focus_hint,
            page_hint,
        )
    elif decision_mode == "vision":
        prompt = build_vision_prompt(
            request.goal,
            request.max_actions,
            observation.width,
            observation.height,
            input_focus_hint,
            page_hint,
        )
    elif decision_mode == "vision_ocr":
        prompt = build_vision_ocr_prompt(
            request.goal,
            observation.ocr_view,
            observation.structure_view,
            observation.ui_view,
            observation.width,
            observation.height,
            request.max_actions,
            request.image_labels,
            input_focus_hint,
            page_hint,
            region=observation.region,
        )
    else:
        raise AdbError("unknown decision_mode: {}".format(request.decision_mode))
    try:
        if request.text_only or not request.images:
            response_text = call_llm_text(
                llm_config,
                prompt,
            )
        else:
            response_text = call_llm_vision_multi(
                llm_config,
                prompt,
                request.images,
            )
    except LlmError as exc:
        raise AdbError(str(exc)) from exc

    try:
        decision = parse_decision_text(response_text)
    except SchemaError as exc:
        raise AdbError(str(exc)) from exc

    if len(decision.actions) > request.max_actions:
        decision = Decision(
            actions=decision.actions[: request.max_actions],
            raw_text=decision.raw_text,
            done=decision.done,
            done_reason=decision.done_reason,
        )

    try:
        validate_actions(decision.actions)
        validate_actions_for_mode(decision.actions, decision_mode)
    except SchemaError as exc:
        raise AdbError(str(exc)) from exc

    return DecisionResponse(
        decision=decision,
        prompt=prompt,
        response_text=response_text,
        decision_mode=decision_mode,
    )
