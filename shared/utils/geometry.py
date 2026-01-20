from shared.errors import AdbError


def clamp(value, low, high):
    return max(low, min(high, value))


def bounds_center(bounds):
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def coerce_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AdbError("invalid {} value".format(label)) from exc


def scale_coord(value, max_value):
    coord = coerce_float(value, "coordinate")
    if 0 <= coord <= 1:
        coord = coord * max_value
    return int(round(coord))
