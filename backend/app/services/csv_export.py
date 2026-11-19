"""CSV downloads that are safe to open in a spreadsheet.

Text that a spreadsheet would run as a formula (starting with = + - @, a tab or a carriage return) is
prefixed with a quote, so a value typed by a citizen or a staff member can never execute when someone
opens an export. A byte order mark is added so Excel reads UTF-8 names and addresses correctly.
"""

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import Response

EXPORT_LIMIT = 5000


def csv_cell(value) -> str:
    """One CSV cell: empty for None, UTC text for a datetime, and formula-neutralised text otherwise."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_response(
    header: Sequence[str], rows: Iterable[Sequence], filename_prefix: str, *, truncated: bool = False
) -> Response:
    """A CSV attachment. `truncated` is reported in X-Export-Truncated so a screen can warn that rows were cut."""
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_cell(v) for v in row])
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_prefix}-{stamp}.csv"',
            "Cache-Control": "no-store",
            "X-Export-Truncated": "true" if truncated else "false",
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Truncated",
        },
    )
