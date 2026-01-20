import json


def build_vision_ocr_prompt(
    goal,
    ocr_view,
    structure_view,
    ui_view,
    width,
    height,
    max_actions,
    image_labels,
    input_focus_hint,
    page_hint,
    region=None,
):
    payload = {
        "screen": {"width": width, "height": height},
        "ocr_view": ocr_view,
        "structure_view": structure_view,
    }
    if region:
        payload["region"] = {
            "x1": region[0],
            "y1": region[1],
            "x2": region[2],
            "y2": region[3],
        }
    if ui_view is not None:
        payload["ui_view"] = ui_view
    if input_focus_hint is not None:
        payload["input_focus_hint"] = input_focus_hint
    if page_hint is not None:
        payload["page_hint"] = page_hint
    images_text = ""
    if image_labels:
        lines = ["Images in order:"]
        for index, label in enumerate(image_labels, start=1):
            lines.append("{}. {}".format(index, label))
        images_text = "\n".join(lines) + "\n"
    if image_labels:
        lead = "Use the screenshot plus OCR/structure data "
    else:
        lead = "Use the OCR/structure data (no images provided) "
    return (
        "You are an Android UI assistant. " + lead +
        "to decide the next UI actions.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "done": false,\n'
        '  "actions": [\n'
        '    {{"type": "tap", "x": 120, "y": 340, "reason": "...", "confidence": 0.0}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        "- Coordinates are absolute pixels relative to the image size.\n"
        "- 0,0 is top-left; width,height is bottom-right.\n"
        '- Allowed types: "tap", "swipe", "text", "keyevent", "wait".\n'
        "- For swipe, use x1,y1,x2,y2 and optional duration_ms.\n"
        "- For text, use value; for keyevent, use keycode; for wait, use seconds.\n"
        "- Do not use target_id/element_id in this mode.\n"
        "- If region is present, OCR/structure coordinates are crop-relative; "
        "actions still use full-screen coordinates (add x1,y1).\n"
        "- UIAutomator bounds, if present, are full-screen coordinates.\n"
        "- If the goal is achieved, set done=true and return an empty actions list.\n"
        "- done_reason is optional when done=true.\n"
        "- At most {max_actions} actions.\n"
        "- If unsure, return an empty actions list.\n"
        "- OCR view, structure view, and UIAutomator view have equal priority.\n"
        "- Only use text actions when input_focus_hint.focused is true.\n"
        "- If text is needed and input_focus_hint.focused is false, tap the input field first.\n"
        "Goal: {goal}\n"
        "{images_text}"
        "OCR + structure data (JSON):\n"
        "{payload}\n"
    ).format(
        max_actions=max_actions,
        goal=goal,
        images_text=images_text,
        payload=json.dumps(payload, ensure_ascii=False),
    )
