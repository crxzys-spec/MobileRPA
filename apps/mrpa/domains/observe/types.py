from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Observation:
    png_bytes: bytes
    width: int
    height: int
    region: Optional[Tuple[int, int, int, int]]
    elements: List[Dict[str, Any]]
    ocr_payload: Optional[Dict[str, Any]]
    ocr_view: Dict[str, Any]
    structure_view: Dict[str, Any]
    ui_view: Optional[Dict[str, Any]]

    def context(self) -> Dict[str, Any]:
        context = {
            "screen": {"width": self.width, "height": self.height},
            "ocr_view": self.ocr_view,
            "structure_view": self.structure_view,
        }
        if self.region:
            context["region"] = {
                "x1": self.region[0],
                "y1": self.region[1],
                "x2": self.region[2],
                "y2": self.region[3],
            }
        if self.ui_view is not None:
            context["ui_view"] = self.ui_view
        return context
