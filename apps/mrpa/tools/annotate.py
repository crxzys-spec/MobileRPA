from pathlib import Path

from shared.errors import AdbError
from shared.text import is_ascii
from shared.utils.geometry import clamp, scale_coord
from infra.image.image import ensure_cv2


def draw_label(image, text, x, y, color):
    cv2, _ = ensure_cv2()
    height, width = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.6
    thickness = 2
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    x = clamp(x, 0, max(0, width - text_width - 1))
    y = clamp(y, text_height + baseline, max(text_height + baseline, height - 1))
    cv2.putText(
        image,
        text,
        (x, y),
        font,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def annotate_actions(image, actions, width, height):
    cv2, _ = ensure_cv2()
    colors = [
        (0, 0, 255),
        (0, 128, 255),
        (0, 200, 0),
        (255, 128, 0),
        (255, 0, 255),
    ]
    text_actions = []
    for index, action in enumerate(actions, start=1):
        action_type = action.get("type")
        color = colors[(index - 1) % len(colors)]
        if action_type == "tap":
            x = clamp(scale_coord(action.get("x"), width), 0, width - 1)
            y = clamp(scale_coord(action.get("y"), height), 0, height - 1)
            cv2.circle(image, (x, y), 16, color, 2)
            cv2.circle(image, (x, y), 3, color, -1)
            draw_label(image, str(index), x + 10, y - 10, color)
            continue
        if action_type == "swipe":
            x1 = clamp(scale_coord(action.get("x1"), width), 0, width - 1)
            y1 = clamp(scale_coord(action.get("y1"), height), 0, height - 1)
            x2 = clamp(scale_coord(action.get("x2"), width), 0, width - 1)
            y2 = clamp(scale_coord(action.get("y2"), height), 0, height - 1)
            cv2.arrowedLine(image, (x1, y1), (x2, y2), color, 2, tipLength=0.2)
            draw_label(image, str(index), x1 + 10, y1 - 10, color)
            continue
        if action_type:
            text_actions.append("{}:{}".format(index, action_type))
    if text_actions:
        start_y = 30
        for offset, item in enumerate(text_actions):
            draw_label(image, item, 10, start_y + offset * 24, (255, 255, 255))


def annotate_elements(image, elements, width, height):
    cv2, _ = ensure_cv2()
    colors = [
        (0, 255, 0),
        (0, 255, 255),
        (255, 0, 0),
        (255, 128, 0),
        (255, 0, 255),
    ]
    for index, element in enumerate(elements, start=1):
        color = colors[(index - 1) % len(colors)]
        bounds = element.get("bounds")
        if bounds and len(bounds) == 4:
            try:
                vals = [float(value) for value in bounds]
            except (TypeError, ValueError):
                vals = None
            if vals:
                if max(vals) <= 1:
                    x1 = clamp(int(round(vals[0] * width)), 0, width - 1)
                    y1 = clamp(int(round(vals[1] * height)), 0, height - 1)
                    x2 = clamp(int(round(vals[2] * width)), 0, width - 1)
                    y2 = clamp(int(round(vals[3] * height)), 0, height - 1)
                else:
                    x1 = clamp(int(round(vals[0])), 0, width - 1)
                    y1 = clamp(int(round(vals[1])), 0, height - 1)
                    x2 = clamp(int(round(vals[2])), 0, width - 1)
                    y2 = clamp(int(round(vals[3])), 0, height - 1)
            else:
                continue
        else:
            x1 = clamp(scale_coord(element.get("x1"), width), 0, width - 1)
            y1 = clamp(scale_coord(element.get("y1"), height), 0, height - 1)
            x2 = clamp(scale_coord(element.get("x2"), width), 0, width - 1)
            y2 = clamp(scale_coord(element.get("y2"), height), 0, height - 1)
        if x2 <= x1 or y2 <= y1:
            continue
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = element.get("label") or element.get("type") or "element"
        text = element.get("text")
        if text and is_ascii(text):
            label = "{} {}".format(index, text[:12])
        else:
            label = "{} {}".format(index, label)
        draw_label(image, label, x1 + 6, y1 + 22, color)


def annotate_structure(image, structure, width, height, ocr_threshold=0.0):
    cv2, _ = ensure_cv2()
    if not isinstance(structure, dict):
        raise AdbError("structure payload missing; use --ocr-raw with remote OCR")
    box_list = structure.get("boxes")
    if isinstance(box_list, list):
        type_colors = {
            "layout": (255, 0, 255),
            "region": (0, 128, 255),
            "image": (0, 255, 255),
            "ocr": (0, 200, 0),
            "table": (0, 165, 255),
            "seal": (0, 0, 255),
            "chart": (255, 128, 0),
            "formula": (128, 0, 255),
        }
        for index, item in enumerate(box_list, start=1):
            if not isinstance(item, dict):
                continue
            bounds = item.get("bounds")
            if not bounds or len(bounds) != 4:
                continue
            score = item.get("score")
            box_type = str(item.get("type") or "box")
            if box_type == "ocr" and score is not None:
                if float(score) < float(ocr_threshold or 0):
                    continue
            try:
                vals = [float(value) for value in bounds]
            except (TypeError, ValueError):
                continue
            if max(vals) <= 1:
                x1 = clamp(int(round(vals[0] * width)), 0, width - 1)
                y1 = clamp(int(round(vals[1] * height)), 0, height - 1)
                x2 = clamp(int(round(vals[2] * width)), 0, width - 1)
                y2 = clamp(int(round(vals[3] * height)), 0, height - 1)
            else:
                x1 = clamp(int(round(vals[0])), 0, width - 1)
                y1 = clamp(int(round(vals[1])), 0, height - 1)
                x2 = clamp(int(round(vals[2])), 0, width - 1)
                y2 = clamp(int(round(vals[3])), 0, height - 1)
            if x2 <= x1 or y2 <= y1:
                continue
            color = type_colors.get(box_type, (255, 255, 255))
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label_text = item.get("text") or item.get("label")
            prefix = box_type.upper()[:3]
            label = "{}{}".format(prefix, index)
            if label_text and is_ascii(str(label_text)):
                label = "{}:{}".format(label, str(label_text)[:12])
            draw_label(image, label, x1 + 6, y1 + 22, color)
        return
    groups = [
        ("layout_boxes", "L", (255, 0, 255)),
        ("region_boxes", "R", (0, 128, 255)),
        ("images", "IMG", (0, 255, 255)),
    ]
    for key, prefix, color in groups:
        boxes = structure.get(key) or []
        if not isinstance(boxes, list):
            continue
        for index, item in enumerate(boxes, start=1):
            if not isinstance(item, dict):
                continue
            bounds = item.get("bounds")
            if not bounds or len(bounds) != 4:
                continue
            try:
                vals = [float(value) for value in bounds]
            except (TypeError, ValueError):
                continue
            if max(vals) <= 1:
                x1 = clamp(int(round(vals[0] * width)), 0, width - 1)
                y1 = clamp(int(round(vals[1] * height)), 0, height - 1)
                x2 = clamp(int(round(vals[2] * width)), 0, width - 1)
                y2 = clamp(int(round(vals[3] * height)), 0, height - 1)
            else:
                x1 = clamp(int(round(vals[0])), 0, width - 1)
                y1 = clamp(int(round(vals[1])), 0, height - 1)
                x2 = clamp(int(round(vals[2])), 0, width - 1)
                y2 = clamp(int(round(vals[3])), 0, height - 1)
            if x2 <= x1 or y2 <= y1:
                continue
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label_text = item.get("label")
            label = "{}{}".format(prefix, index)
            if label_text and is_ascii(str(label_text)):
                label = "{}:{}".format(label, str(label_text)[:12])
            draw_label(image, label, x1 + 6, y1 + 22, color)
    ocr = structure.get("ocr") or {}
    lines = ocr.get("lines") or []
    if isinstance(lines, list):
        color = (0, 200, 0)
        for index, line in enumerate(lines, start=1):
            if not isinstance(line, dict):
                continue
            bounds = line.get("bounds")
            if not bounds or len(bounds) != 4:
                continue
            score = line.get("score")
            if score is not None and float(score) < float(ocr_threshold or 0):
                continue
            try:
                vals = [float(value) for value in bounds]
            except (TypeError, ValueError):
                continue
            if max(vals) <= 1:
                x1 = clamp(int(round(vals[0] * width)), 0, width - 1)
                y1 = clamp(int(round(vals[1] * height)), 0, height - 1)
                x2 = clamp(int(round(vals[2] * width)), 0, width - 1)
                y2 = clamp(int(round(vals[3] * height)), 0, height - 1)
            else:
                x1 = clamp(int(round(vals[0])), 0, width - 1)
                y1 = clamp(int(round(vals[1])), 0, height - 1)
                x2 = clamp(int(round(vals[2])), 0, width - 1)
                y2 = clamp(int(round(vals[3])), 0, height - 1)
            if x2 <= x1 or y2 <= y1:
                continue
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            text = line.get("text") or ""
            if text and is_ascii(str(text)):
                label = "OCR{}:{}".format(index, str(text)[:12])
            else:
                label = "OCR{}".format(index)
            draw_label(image, label, x1 + 6, y1 + 22, color)


def save_image(path, image):
    cv2, _ = ensure_cv2()
    output_path = Path(path)
    if output_path.parent and not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        raise AdbError("failed to write image: {}".format(output_path))
