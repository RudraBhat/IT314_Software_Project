#!/usr/bin/env python3
"""Fail when an environment variable read by code is missing from docs/env-variables.md.

Scans backend/, ai-workers/ (os.getenv / os.environ) and frontend/src, frontend/next.config.ts
(process.env.X). Run from the repository root:  python scripts/check_env_docs.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "env-variables.md").read_text(encoding="utf-8")
IGNORE = {"NODE_ENV", "PATH", "HOME", "PORT", "HOSTNAME", "CI"}  # set by the platform, not by us

PY = re.compile(r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z][A-Z0-9_]+)["']|os\.environ\[\s*["']([A-Z][A-Z0-9_]+)["']""")
JS = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)")

used: dict[str, set[str]] = {}
for base, pattern, suffixes in (
    (ROOT / "backend" / "app", PY, {".py"}),
    (ROOT / "backend" / "main.py", PY, {".py"}),
    (ROOT / "ai-workers", PY, {".py"}),
    (ROOT / "frontend" / "src", JS, {".ts", ".tsx"}),
    (ROOT / "frontend" / "next.config.ts", JS, {".ts"}),
):
    files = [base] if base.is_file() else [
        p for p in base.rglob("*")
        if p.suffix in suffixes and not any(part in {"node_modules", "venv", ".venv"} for part in p.parts)
    ]
    for path in files:
        if "/model/" in path.as_posix() or "/tests/" in path.as_posix():
            continue
        for match in pattern.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            name = next(g for g in match.groups() if g)
            used.setdefault(name, set()).add(str(path.relative_to(ROOT)))

missing = sorted(n for n in used if n not in IGNORE and f"`{n}`" not in DOC)
if missing:
    print("Environment variables used in code but not documented in docs/env-variables.md:")
    for name in missing:
        print(f"  - {name}  (read in {', '.join(sorted(used[name]))})")
    sys.exit(1)
print(f"OK: {len(used)} environment variables are documented.")
