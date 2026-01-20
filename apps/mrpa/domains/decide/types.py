from dataclasses import dataclass
from typing import List

from mrpa.contracts import Decision
from mrpa.domains.observe.types import Observation


@dataclass
class DecisionRequest:
    goal: str
    observation: Observation
    max_actions: int
    image_labels: List[str]
    images: List[bytes]
    decision_mode: str = "vision_ocr"
    text_only: bool = False


@dataclass
class DecisionResponse:
    decision: Decision
    prompt: str
    response_text: str
    decision_mode: str
