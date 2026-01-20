def build_vision_label_prompt(goal, max_elements, width, height):
    return (
        "You are an Android UI analyst. Identify visible UI elements in the screenshot "
        "and return their bounding boxes with labels.\n"
        "Return JSON only with this schema:\n"
        "{{\n"
        '  "elements": [\n'
        '    {{"label": "Search", "type": "button", "x1": 0.1, "y1": 0.1, '
        '"x2": 0.2, "y2": 0.2, "description": "...", "confidence": 0.0}}\n'
        "  ]\n"
        "}}\n"
        "Constraints:\n"
        "- Coordinates are normalized (0..1) relative to image size.\n"
        "- 0,0 is top-left; 1,1 is bottom-right.\n"
        '- type should be one of: "button", "icon", "text", "input", "list", '
        '"tab", "image", "unknown".\n'
        "- At most {max_elements} elements.\n"
        "- If unsure, return an empty elements list.\n"
        "Goal context: {goal}\n"
        "Image size: {width}x{height}\n"
    ).format(max_elements=max_elements, goal=goal, width=width, height=height)
