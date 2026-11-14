"""Shared helpers for endpoints that receive an image as the raw request body.

Used by DM photo analysis (routers/dm/ai.py) and citizen evidence upload (routers/citizen.py).
The client-declared content type and file name are never trusted: the type is sniffed from the
bytes and the name is reduced to a short printable base name.
"""

from urllib.parse import unquote

from fastapi import Request

from app.errors import ApiError


def sniff_image_type(data: bytes) -> str | None:
    """Identify JPEG, PNG or WebP from the first bytes; the client-declared type is not trusted."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


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
