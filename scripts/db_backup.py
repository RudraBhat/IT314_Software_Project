#!/usr/bin/env python3
"""Database backup and restore for ResQ (S3-12). Owner: Shlok.

Wraps the PostgreSQL client tools (pg_dump / pg_restore, version 16 or newer) so a backup can be taken
before a migration or release and restored into a separate database to check it.

  python scripts/db_backup.py backup                              # uses DATABASE_URL, writes backups/<db>-<UTC time>.dump
  python scripts/db_backup.py backup --database-url URL --out backups/pre-v1.0.0.dump
  python scripts/db_backup.py restore --file backups/pre-v1.0.0.dump --target-url URL_OF_drch_restore

Safety:
* The password is passed to the tools through PGPASSWORD, never on the command line.
* restore refuses a target database whose name does not end in "_restore" or "_test", so a backup is
  never restored over a live database by accident. Pass --force only when you really mean to replace
  that database, for example in a declared rollback (docs/operations/runbook-migration.md).
* Backups contain personal data: keep them out of git (backups/ and *.dump are ignored) and delete
  them when they are no longer needed.

On Neon, a branch (docs/operations/runbook-migration.md, Step 1) is the faster rollback point; this script is the
portable copy that also works for the docker-compose fallback.
"""

from __future__ import annotations

import argparse
import os
import shutil
# subprocess runs only the pg_dump / pg_restore binaries found on PATH, with argument lists and no shell.
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

SAFE_RESTORE_SUFFIXES = ("_restore", "_test")
ROOT = Path(__file__).resolve().parents[1]


def split_password(url: str) -> tuple[str, str | None]:
    """Return the URL without its password, and the password (decoded) for PGPASSWORD."""
    parts = urlsplit(url)
    if parts.password is None:
        return url, None
    netloc = parts.hostname or ""
    if parts.username:
        netloc = f"{parts.username}@{netloc}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc)), unquote(parts.password)


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def restore_allowed(target_url: str, force: bool) -> tuple[bool, str]:
    """Whether a restore into target_url may run, with the reason."""
    name = database_name(target_url)
    if not name:
        return False, "the target URL has no database name"
    if name.endswith(SAFE_RESTORE_SUFFIXES):
        return True, f"target database '{name}' is a restore or test database"
    if force:
        return True, f"--force given: database '{name}' will be overwritten"
    return False, (f"refusing to restore into '{name}': the name must end in "
                   f"{' or '.join(SAFE_RESTORE_SUFFIXES)}, or pass --force for a declared rollback")


def default_backup_path(url: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "backups" / f"{database_name(url) or 'database'}-{stamp}.dump"


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        sys.exit(f"ERROR: {name} was not found. Install the PostgreSQL 16 client tools and retry.")
    return path


def _env_with_password(password: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    return env


def backup(database_url: str, out: Path) -> Path:
    url, password = split_password(database_url)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", f"--file={out}", f"--dbname={url}"]
    subprocess.run(cmd, check=True, env=_env_with_password(password))  # nosec B603
    return out


def restore(dump: Path, target_url: str, force: bool) -> None:
    allowed, reason = restore_allowed(target_url, force)
    if not allowed:
        sys.exit(f"ERROR: {reason}")
    if not dump.is_file():
        sys.exit(f"ERROR: backup file not found: {dump}")
    print(f"Restoring {dump.name}: {reason}")
    url, password = split_password(target_url)
    cmd = [_tool("pg_restore"), "--clean", "--if-exists", "--no-owner", "--no-privileges",
           f"--dbname={url}", str(dump)]
    subprocess.run(cmd, check=True, env=_env_with_password(password))  # nosec B603


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up or restore the ResQ database")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="write a pg_dump custom-format backup")
    b.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    b.add_argument("--out", type=Path)
    r = sub.add_parser("restore", help="restore a backup into a separate database")
    r.add_argument("--file", type=Path, required=True)
    r.add_argument("--target-url", required=True)
    r.add_argument("--force", action="store_true", help="allow a target name without _restore/_test")
    args = parser.parse_args()

    if args.command == "backup":
        if not args.database_url:
            parser.error("set DATABASE_URL or pass --database-url")
        out = backup(args.database_url, args.out or default_backup_path(args.database_url))
        print(f"Backup written to {out}")
    else:
        restore(args.file, args.target_url, args.force)
        print("Restore finished. Check it with: python -m app.cli verify-audit (against the restored database)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
