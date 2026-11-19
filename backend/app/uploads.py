"""Shared helpers for endpoints that receive an image as the raw request body.

Used by DM photo analysis (routers/dm/ai.py) and citizen evidence upload (routers/citizen.py).
The client-declared content type and file name are never trusted: the type is sniffed from the
bytes and the name is reduced to a short printable base name.
"""

import struct
from urllib.parse import unquote

from fastapi import Request

from app.errors import ApiError


def _invalid_image() -> ApiError:
    return ApiError(415, "INVALID_IMAGE", "The file is not a readable JPEG, PNG or WebP image.")


def sniff_image_type(data: bytes) -> str | None:
    """Identify JPEG, PNG or WebP from the first bytes; the client-declared type is not trusted."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg_orientation_segment(exif: bytes) -> bytes:
    """Rebuild an APP1 segment holding only the EXIF orientation tag, or b"" if there is none.

    Phones record rotation in EXIF; keeping that one tag stops stripped photos showing sideways.
    """
    if not exif.startswith(b"Exif\0\0") or len(exif) < 14:
        return b""
    tiff = exif[6:]
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if order is None:
        return b""
    try:
        (ifd,) = struct.unpack(order + "I", tiff[4:8])
        (count,) = struct.unpack(order + "H", tiff[ifd : ifd + 2])
        for i in range(count):
            entry = tiff[ifd + 2 + 12 * i : ifd + 14 + 12 * i]
            tag, kind, n = struct.unpack(order + "HHI", entry[:8])
            if tag == 0x0112 and kind == 3 and n == 1:
                (value,) = struct.unpack(order + "H", entry[8:10])
                if not 1 <= value <= 8:
                    return b""
                body = (
                    b"Exif\0\0"
                    + tiff[:2]
                    + struct.pack(order + "HI", 42, 8)
                    + struct.pack(order + "H", 1)
                    + struct.pack(order + "HHIHH", 0x0112, 3, 1, value, 0)
                    + struct.pack(order + "I", 0)
                )
                return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    except struct.error:
        return b""
    return b""


def _strip_jpeg(data: bytes) -> bytes:
    # Drop APP1 (EXIF with GPS, camera serials; XMP), APP13 (IPTC) and comments. Keep JFIF, ICC
    # colour profiles and every coding segment; image data after SOS is copied unchanged.
    out = bytearray(data[:2])
    pos = 2
    orientation = b""
    head = 2  # where the orientation APP1 goes: after SOI, or after a leading JFIF APP0
    while True:
        while pos < len(data) and data[pos] == 0xFF and pos + 1 < len(data) and data[pos + 1] == 0xFF:
            pos += 1  # fill bytes between segments
        if pos + 4 > len(data) or data[pos] != 0xFF:
            raise _invalid_image()
        marker = data[pos + 1]
        if marker == 0xD9:  # EOI with no scan
            raise _invalid_image()
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[pos : pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        end = pos + 2 + length
        if length < 2 or end > len(data):
            raise _invalid_image()
        segment = data[pos:end]
        if marker == 0xE1:
            orientation = orientation or _jpeg_orientation_segment(data[pos + 4 : end])
        elif marker not in (0xED, 0xFE):
            if marker == 0xDA:  # start of scan: add the orientation, then copy the rest verbatim
                return bytes(out[:head]) + orientation + bytes(out[head:]) + data[pos:]
            if marker == 0xE0 and len(out) == 2:
                head = 2 + len(segment)
            out += segment
        pos = end


_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def _strip_png(data: bytes) -> bytes:
    # Remove text, EXIF and timestamp chunks; anything after IEND is discarded.
    out = bytearray(data[:8])
    pos = 8
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise _invalid_image()
        if kind not in _PNG_DROP:
            out += data[pos:end]
        if kind == b"IEND":
            return bytes(out)
        pos = end
    raise _invalid_image()


def _strip_webp(data: bytes) -> bytes:
    # Remove the EXIF and XMP chunks and clear their flags in the VP8X header.
    chunks = bytearray()
    pos = 12
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        end = pos + 8 + size + (size & 1)
        if pos + 8 + size > len(data):
            raise _invalid_image()
        chunk = bytearray(data[pos:end])
        if kind == b"VP8X" and size >= 1:
            chunk[8] &= ~0x0C & 0xFF
        if kind not in (b"EXIF", b"XMP "):
            chunks += chunk
        pos = end
    if not chunks:
        raise _invalid_image()
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + bytes(chunks)


def strip_image_metadata(data: bytes, mime: str) -> bytes:
    """Remove location, camera and text metadata from a JPEG, PNG or WebP without re-encoding it.

    Pixels are untouched. A file whose structure cannot be walked is refused (415 INVALID_IMAGE)
    rather than stored with its metadata intact.
    """
    if mime == "image/jpeg":
        return _strip_jpeg(data)
    if mime == "image/png":
        return _strip_png(data)
    if mime == "image/webp":
        return _strip_webp(data)
    raise _invalid_image()


def safe_filename(raw: str | None) -> str:
    """Decode the percent-encoded X-Filename header and keep a short, printable base name."""
    name = unquote(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')[:100].strip()
    return name or "photo"


async def read_capped_body(request: Request, limit: int) -> bytes:
    """Read the request body but stop as soon as it passes `limit`, so an oversized upload never sits in memory."""
    too_large = ApiError(413, "FILE_TOO_LARGE", f"The file exceeds the {limit // (1024 * 1024)} MB limit.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)
