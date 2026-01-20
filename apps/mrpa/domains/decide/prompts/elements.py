def build_decision_prompt(goal, elements, max_actions, input_focus_hint, page_hint):
    lines = []
    for element in elements:
        element_id = element.get("id", "")
        element_type = element.get("type", "unknown")
        text = element.get("text", "")
        bounds = element.get("bounds")
        center = element.get("center")
        confidence = element.get("confidence")
        source = element.get("source", "")
        lines.append(
            "id={id} type={type} text={text} bounds={bounds} center={center} "
            "confidence={conf} source={source}".format(
                id=element_id,
                type=element_type,
                text=text,
                bounds=bounds,
                center=center,
                conf=confidence,
                source=source,
            )
        )
    elements_text = "\n".join(lines) if lines else "(no elements)"
    return (
        "You are an Android UI decision assistant. Choose the next actions to "
        "achieve the goal based on the provided UI elements.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "done": false,\n'
        '  "actions": [\n'
        '    {{"type": "tap_element", "target_id": "id", "reason": "...", "confidence": 0.0}},\n'
        '    {{"type": "text", "value": "..."}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        '- Allowed types: "tap_element", "tap", "swipe", "text", "keyevent", "wait".\n'
        '- For tap_element, use target_id from the element list.\n'
        '- For tap, use target_id/element_id only (do not use x/y).\n'
        "- For swipe, use x1,y1,x2,y2 and optional duration_ms.\n"
        "- For text, use value. For keyevent, use keycode.\n"
        "- If the goal is achieved, set done=true and return an empty actions list.\n"
        "- done_reason is optional when done=true.\n"
        "- At most {max_actions} actions.\n"
        "- If unsure, return an empty actions list.\n"
        "- Only use text actions when input_focus_hint.focused is true.\n"
        "- If text is needed and input_focus_hint.focused is false, tap the input field first.\n"
        "Goal: {goal}\n"
        "Input focus hint (JSON): {input_focus_hint}\n"
        "Page hint (JSON): {page_hint}\n"
        "Elements:\n"
        "{elements}\n"
    ).format(
        max_actions=max_actions,
        goal=goal,
        elements=elements_text,
        input_focus_hint=input_focus_hint,
        page_hint=page_hint,
    )
