from infra.image.image import decode_png, encode_png, ensure_cv2


def resize_png_bytes(png_bytes: bytes, max_side: int = 720) -> bytes:
    if not png_bytes:
        return png_bytes
    if max_side <= 0:
        return png_bytes
    image = decode_png(png_bytes)
    height, width = image.shape[:2]
    max_dim = max(height, width)
    if max_dim <= max_side:
        return png_bytes
    scale = max_side / float(max_dim)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    cv2, _ = ensure_cv2()
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    return encode_png(resized)
