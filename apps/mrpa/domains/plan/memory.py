import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from mrpa.domains.observe.types import Observation
from mrpa.utils import build_page_hint, detect_input_focus
from mrpa.domains.plan.types import PlanState


def summarize_observation(
    observation: Observation,
    max_elements: int = 20,
    max_nodes: int = 20,
    max_text_len: int = 80,
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "screen": {"width": observation.width, "height": observation.height},
    }
    summary["input_focus_hint"] = detect_input_focus(
        observation.elements,
        observation.height,
        ocr_payload=observation.ocr_payload,
        ui_view=observation.ui_view,
    )
    summary["page_hint"] = build_page_hint(
        observation.elements,
        observation.height,
        ocr_payload=observation.ocr_payload,
        ui_view=observation.ui_view,
    )
    if observation.region:
        summary["region"] = {
            "x1": observation.region[0],
            "y1": observation.region[1],
            "x2": observation.region[2],
            "y2": observation.region[3],
        }
    elements_summary: List[Dict[str, Any]] = []
    for element in observation.elements or []:
        text = element.get("text")
        if not text:
            continue
        text_value = str(text).strip()
        if not text_value:
            continue
        elements_summary.append(
            {
                "id": element.get("id"),
                "text": text_value[:max_text_len],
                "bounds": element.get("bounds"),
                "confidence": element.get("confidence"),
                "source": element.get("source"),
            }
        )
        if len(elements_summary) >= max_elements:
            break
    summary["elements"] = elements_summary

    ui_summary: List[Dict[str, Any]] = []
    ui_view = observation.ui_view
    if isinstance(ui_view, dict):
        for node in ui_view.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            text = node.get("text") or node.get("content_desc")
            if not text:
                continue
            text_value = str(text).strip()
            if not text_value:
                continue
            ui_summary.append(
                {
                    "text": text_value[:max_text_len],
                    "resource_id": node.get("resource_id"),
                    "bounds": node.get("bounds"),
                    "class": node.get("class"),
                }
            )
            if len(ui_summary) >= max_nodes:
                break
    if ui_summary:
        summary["ui_nodes"] = ui_summary
    return summary


@dataclass
class MemoryStore:
    path: Optional[Path] = None
    max_entries: int = 200
    entries: List[Dict[str, Any]] = field(default_factory=list)
    plan: Optional[PlanState] = None
    version: int = 1

    def load(self) -> "MemoryStore":
        if not self.path or not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self
        if isinstance(data, dict):
            plan_data = data.get("plan")
            if isinstance(plan_data, dict):
                self.plan = PlanState.from_dict(plan_data)
            entries = data.get("entries")
            if isinstance(entries, list):
                self.entries = [item for item in entries if isinstance(item, dict)]
        return self

    def save(self) -> None:
        if not self.path:
            return
        payload = {
            "version": self.version,
            "plan": self.plan.to_dict() if self.plan else None,
            "entries": self.entries,
        }
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def update_plan(self, plan: Optional[PlanState]) -> None:
        self.plan = plan
        self.save()

    def append_entry(self, entry: Dict[str, Any]) -> None:
        self.entries.append(entry)
        if self.max_entries and self.max_entries > 0:
            if len(self.entries) > self.max_entries:
                self.entries = self.entries[-self.max_entries :]
        self.save()

    def tail(self, count: int = 5) -> List[Dict[str, Any]]:
        if count <= 0:
            return []
        return self.entries[-count:]
