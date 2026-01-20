from typing import Any, Optional, Tuple

from shared.errors import AdbError
from shared.utils.geometry import clamp


def resolve_region(
    region: Any, width: int, height: int
) -> Optional[Tuple[int, int, int, int]]:
    if not region:
        return None

    def to_abs(value: Any, max_value: int) -> int:
        value = float(value)
        if 0 <= value <= 1:
            return int(round(value * max_value))
        return int(round(value))

    if isinstance(region, str):
        parts = [part.strip() for part in region.split(",") if part.strip()]
        if len(parts) != 4:
            raise AdbError("region must be x1,y1,x2,y2")
        left = to_abs(parts[0], width)
        top = to_abs(parts[1], height)
        right = to_abs(parts[2], width)
        bottom = to_abs(parts[3], height)
    elif isinstance(region, (list, tuple)):
        if len(region) != 4:
            raise AdbError("region must have 4 values")
        left = to_abs(region[0], width)
        top = to_abs(region[1], height)
        right = to_abs(region[2], width)
        bottom = to_abs(region[3], height)
    elif isinstance(region, dict):
        if all(key in region for key in ("x1", "y1", "x2", "y2")):
            left = to_abs(region["x1"], width)
            top = to_abs(region["y1"], height)
            right = to_abs(region["x2"], width)
            bottom = to_abs(region["y2"], height)
        elif all(key in region for key in ("x", "y", "w", "h")):
            left = to_abs(region["x"], width)
            top = to_abs(region["y"], height)
            region_width = to_abs(region["w"], width)
            region_height = to_abs(region["h"], height)
            right = left + region_width
            bottom = top + region_height
        else:
            raise AdbError("invalid region keys")
    else:
        raise AdbError("invalid region")

    left = clamp(left, 0, width - 1)
    top = clamp(top, 0, height - 1)
    right = clamp(right, left + 1, width)
    bottom = clamp(bottom, top + 1, height)
    return left, top, right, bottom


def crop_image(image, region: Tuple[int, int, int, int]):
    left, top, right, bottom = region
    return image[top:bottom, left:right], (left, top)
