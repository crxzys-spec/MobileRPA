from infra.image.image import decode_png, ensure_cv2


def compare_png_bytes(before_png: bytes, after_png: bytes, pixel_threshold: int = 10) -> dict:
    cv2, np = ensure_cv2()
    before = decode_png(before_png)
    after = decode_png(after_png)
    if before.shape != after.shape:
        return {"changed_ratio": 1.0, "mean_abs_diff": 1.0, "size_changed": True}
    diff = cv2.absdiff(before, after)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    mean_abs_diff = float(np.mean(gray)) / 255.0
    if gray.size:
        changed = gray > int(pixel_threshold)
        changed_ratio = float(np.count_nonzero(changed)) / float(changed.size)
    else:
        changed_ratio = 0.0
    return {
        "changed_ratio": changed_ratio,
        "mean_abs_diff": mean_abs_diff,
        "size_changed": False,
    }
