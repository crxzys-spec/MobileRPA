import time
from pathlib import Path

from shared.errors import AdbError
from infra.image.image import decode_png, ensure_cv2, load_image


def capture_screen(adb):
    return decode_png(adb.screenshot_bytes())


def match_template(screen, template, region=None):
    cv2, _ = ensure_cv2()
    screen_height, screen_width = screen.shape[:2]
    if region:
        left, top, right, bottom = region
    else:
        left, top, right, bottom = 0, 0, screen_width, screen_height
    if right <= left or bottom <= top:
        raise AdbError("invalid region bounds")
    region_img = screen[top:bottom, left:right]
    template_height, template_width = template.shape[:2]
    region_height, region_width = region_img.shape[:2]
    if template_height > region_height or template_width > region_width:
        raise AdbError("template larger than search region")
    result = cv2.matchTemplate(region_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    top_left = (left + max_loc[0], top + max_loc[1])
    return {
        "score": float(max_val),
        "top_left": top_left,
        "size": (template_width, template_height),
    }


def match_center(match):
    left, top = match["top_left"]
    width, height = match["size"]
    return left + width // 2, top + height // 2


def find_image(adb, image_path, threshold=0.85, region=None):
    screen = capture_screen(adb)
    template = load_image(image_path)
    match = match_template(screen, template, region=region)
    if match["score"] >= threshold:
        return match
    return None


def wait_for_image(
    adb,
    image_path,
    threshold=0.85,
    timeout=10,
    interval=0.5,
    region=None,
):
    template = load_image(image_path)
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screen(adb)
        match = match_template(screen, template, region=region)
        if match["score"] >= threshold:
            return match
        time.sleep(interval)
    return None


def collect_template_paths(template_dir):
    if not template_dir:
        return []
    base = Path(template_dir)
    if not base.exists():
        return []
    patterns = ("*.png", "*.jpg", "*.jpeg", "*.bmp")
    paths = []
    for pattern in patterns:
        paths.extend(base.glob(pattern))
    return sorted(paths)
