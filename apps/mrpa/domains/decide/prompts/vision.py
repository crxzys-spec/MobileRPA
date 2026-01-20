def build_vision_prompt(goal, max_actions, width, height, input_focus_hint, page_hint):
    return (
        "You are an Android UI assistant. Analyze the screenshot and propose "
        "the next UI actions to achieve the goal.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "done": false,\n'
        '  "actions": [\n'
        '    {{"type": "tap", "x": 0.5, "y": 0.5, "reason": "...", "confidence": 0.0}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        "- Coordinates are normalized (0..1) relative to image size.\n"
        "- 0,0 is top-left; 1,1 is bottom-right.\n"
        '- Allowed types: "tap", "swipe", "text", "keyevent", "wait".\n'
        "- For swipe, use x1,y1,x2,y2 and optional duration_ms.\n"
        "- For text, use value; for keyevent, use keycode; for wait, use seconds.\n"
        "- Do not use target_id/element_id in this mode.\n"
        "- If the goal is achieved, set done=true and return an empty actions list.\n"
        "- done_reason is optional when done=true.\n"
        "- At most {max_actions} actions.\n"
        "- If unsure, return an empty actions list.\n"
        "- Only use text actions when input_focus_hint.focused is true.\n"
        "- If text is needed and input_focus_hint.focused is false, tap the input field first.\n"
        "Goal: {goal}\n"
        "Image size: {width}x{height}\n"
        "Input focus hint (JSON): {input_focus_hint}\n"
        "Page hint (JSON): {page_hint}\n"
    ).format(
        max_actions=max_actions,
        goal=goal,
        width=width,
        height=height,
        input_focus_hint=input_focus_hint,
        page_hint=page_hint,
    )
