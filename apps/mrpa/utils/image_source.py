from pathlib import Path
from typing import Optional, Tuple

from shared.utils.png import png_size


def get_png_bytes(adb, image_path: Optional[str]) -> Tuple[bytes, int, int]:
    if image_path:
        png_bytes = Path(image_path).read_bytes()
    else:
        png_bytes = adb.screenshot_bytes()
    width, height = png_size(png_bytes)
    return png_bytes, width, height
