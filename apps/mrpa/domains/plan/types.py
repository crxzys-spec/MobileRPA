from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlanStep:
    goal: str
    status: str = "pending"
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {"goal": self.goal, "status": self.status}
        if self.note is not None:
            payload["note"] = self.note
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        if not isinstance(data, dict):
            return cls(goal="")
        goal = str(data.get("goal") or "")
        status = str(data.get("status") or "pending")
        note = data.get("note")
        return cls(goal=goal, status=status, note=note)


@dataclass
class PlanState:
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    current_index: int = 0

    def current_step(self) -> Optional[PlanStep]:
        if not self.steps or self.current_index >= len(self.steps):
            return None
        index = max(0, self.current_index)
        return self.steps[index]

    def advance(self) -> None:
        if not self.steps:
            return
        index = max(0, min(self.current_index, len(self.steps) - 1))
        self.steps[index].status = "done"
        self.current_index = index + 1
        if self.current_index < len(self.steps):
            self.steps[self.current_index].status = "in_progress"

    def is_done(self) -> bool:
        return self.current_index >= len(self.steps)

    def _sync_statuses(self) -> None:
        if not self.steps:
            return
        if self.current_index < 0:
            self.current_index = 0
        if self.current_index > len(self.steps):
            self.current_index = len(self.steps)
        for index, step in enumerate(self.steps):
            if index < self.current_index:
                step.status = "done"
            elif index == self.current_index:
                if step.status != "done":
                    step.status = "in_progress"
            else:
                if step.status == "done":
                    step.status = "pending"

    def to_dict(self) -> Dict[str, Any]:
        self._sync_statuses()
        return {
            "goal": self.goal,
            "current_index": self.current_index,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanState":
        if not isinstance(data, dict):
            return cls(goal="", steps=[], current_index=0)
        goal = str(data.get("goal") or "")
        steps_data = data.get("steps") or []
        steps = [PlanStep.from_dict(item) for item in steps_data if isinstance(item, dict)]
        current_index = int(data.get("current_index") or 0)
        state = cls(goal=goal, steps=steps, current_index=current_index)
        state._sync_statuses()
        return state


@dataclass
class SkillSelection:
    name: Optional[str]
    params: Dict[str, Any]
    done: bool = False
    done_reason: Optional[str] = None
    raw_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "params": dict(self.params or {}),
            "done": self.done,
        }
        if self.done_reason is not None:
            payload["done_reason"] = self.done_reason
        return payload


@dataclass
class PlanVerifyResult:
    done: bool
    mode: str
    evidence: List[str]
    reason: Optional[str] = None
    error: Optional[str] = None
    prompt: Optional[str] = None
    response_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "done": self.done,
            "mode": self.mode,
            "evidence": list(self.evidence or []),
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.error is not None:
            payload["error"] = self.error
        return payload
