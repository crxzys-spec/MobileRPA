from shared.errors import AdbError
from shared.utils.png import png_size


def ensure_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise AdbError(
            "opencv-python is required for image recognition. "
            "Install with pip install -r requirements.txt"
        ) from exc
    return cv2, np


def decode_png(png_bytes):
    cv2, np = ensure_cv2()
    data = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise AdbError("failed to decode screenshot")
    return image


def encode_png(image):
    cv2, _ = ensure_cv2()
    success, buffer = cv2.imencode(".png", image)
    if not success:
        raise AdbError("failed to encode PNG")
    return buffer.tobytes()


def load_image(path):
    cv2, _ = ensure_cv2()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise AdbError("failed to load image: {}".format(path))
    return image

