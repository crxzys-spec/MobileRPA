import struct

from shared.errors import AdbError


def png_size(png_bytes):
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise AdbError("image is not a valid PNG")
    width, height = struct.unpack(">II", png_bytes[16:24])
    return int(width), int(height)
