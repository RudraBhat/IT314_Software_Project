#!/usr/bin/env python3
"""Generate the ER diagram of the final schema from the SQL migrations (S3-16). Owner: Zalak.

Reads backend/db/migrations/*.sql in order, follows CREATE TABLE, ALTER TABLE ... ADD/DROP COLUMN and DROP TABLE,
and writes
a Mermaid erDiagram to docs/architecture/er-diagram.md (GitHub renders Mermaid in Markdown). Re-run it after adding a
migration so the diagram in the final report matches the schema:

  python scripts/generate_er_diagram.py            # writes docs/architecture/er-diagram.md
  python scripts/generate_er_diagram.py --check    # exits 1 when docs/architecture/er-diagram.md is out of date

It is a small parser for the DDL style used in this repository, not a full SQL parser.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "backend" / "db" / "migrations"
OUTPUT = ROOT / "docs" / "architecture" / "er-diagram.md"

_COMMENT = re.compile(r"--[^\n]*")
_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)\s*\(", re.IGNORECASE)
_ALTER_ADD = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w.]+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(.+?);",
    re.IGNORECASE | re.DOTALL,
)
_DROP_TABLE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.]+)", re.IGNORECASE)
_ALTER_DROP = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w.]+)\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?",
    re.IGNORECASE,
)
_REFERENCES = re.compile(r"REFERENCES\s+([\w.]+)\s*\(\s*(\w+)", re.IGNORECASE)
_TABLE_CONSTRAINT = re.compile(r"^(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|EXCLUDE)\b", re.IGNORECASE)


@dataclass
class Column:
    name: str
    type: str
    keys: set[str] = field(default_factory=set)


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    references: list[tuple[str, str]] = field(default_factory=list)  # (column, parent table)


def _strip_schema(name: str) -> str:
    return name.split(".")[-1].lower()


def _matching_paren(text: str, open_index: int) -> int:
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced parentheses in CREATE TABLE")


def _split_top_level(body: str) -> list[str]:
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _simple_type(raw: str) -> str:
    """Mermaid attribute types must be one word: VARCHAR(50) -> varchar, TIMESTAMPTZ -> timestamptz."""
    base = re.split(r"[\s(\[]", raw.strip(), maxsplit=1)[0]
    return re.sub(r"\W", "_", base.lower()) or "unknown"


def _apply_column(table: Table, definition: str) -> None:
    tokens = definition.split()
    if len(tokens) < 2:
        return
    column = Column(name=tokens[0].strip('"').lower(), type=_simple_type(" ".join(tokens[1:])))
    upper = definition.upper()
    if "PRIMARY KEY" in upper:
        column.keys.add("PK")
    if re.search(r"\bUNIQUE\b", upper):
        column.keys.add("UK")
    ref = _REFERENCES.search(definition)
    if ref:
        column.keys.add("FK")
        table.references.append((column.name, _strip_schema(ref.group(1))))
    table.columns[column.name] = column


def _apply_table_constraint(table: Table, definition: str) -> None:
    upper = definition.upper()
    names = re.search(r"\(([^)]*)\)", definition)
    columns = [c.strip().strip('"').lower() for c in names.group(1).split(",")] if names else []
    if "PRIMARY KEY" in upper:
        for c in columns:
            if c in table.columns:
                table.columns[c].keys.add("PK")
    elif upper.startswith("FOREIGN KEY") or ("FOREIGN KEY" in upper):
        ref = _REFERENCES.search(definition)
        if ref and columns:
            for c in columns:
                if c in table.columns:
                    table.columns[c].keys.add("FK")
            table.references.append((columns[0], _strip_schema(ref.group(1))))
    elif upper.startswith("UNIQUE") and len(columns) == 1 and columns[0] in table.columns:
        table.columns[columns[0]].keys.add("UK")


def parse(sql_texts: list[str]) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for raw in sql_texts:
        sql = _COMMENT.sub("", raw)
        for match in _CREATE.finditer(sql):
            name = _strip_schema(match.group(1))
            close = _matching_paren(sql, match.end() - 1)
            table = tables.setdefault(name, Table(name))
            for item in _split_top_level(sql[match.end():close]):
                if _TABLE_CONSTRAINT.match(item):
                    _apply_table_constraint(table, item)
                else:
                    _apply_column(table, item)
        for match in _ALTER_ADD.finditer(sql):
            name = _strip_schema(match.group(1))
            if name in tables:
                _apply_column(tables[name], match.group(2).strip())
        # Removals come last in a migration file: a later migration may drop what an earlier one created.
        for match in _ALTER_DROP.finditer(sql):
            name, column = _strip_schema(match.group(1)), match.group(2).lower()
            if name in tables:
                tables[name].columns.pop(column, None)
                tables[name].references = [r for r in tables[name].references if r[0] != column]
        for match in _DROP_TABLE.finditer(sql):
            dropped = _strip_schema(match.group(1))
            tables.pop(dropped, None)
            for table in tables.values():
                table.references = [r for r in table.references if r[1] != dropped]
    return tables


def render(tables: dict[str, Table]) -> str:
    lines = ["erDiagram"]
    for table in sorted(tables.values(), key=lambda t: t.name):
        lines.append(f"    {table.name} {{")
        for col in table.columns.values():
            keys = ", ".join(k for k in ("PK", "FK", "UK") if k in col.keys)
            lines.append(f"        {col.type} {col.name}{' ' + keys if keys else ''}")
        lines.append("    }")
    seen = set()
    for table in sorted(tables.values(), key=lambda t: t.name):
        for column, parent in table.references:
            if parent not in tables or (parent, table.name, column) in seen:
                continue
            seen.add((parent, table.name, column))
            lines.append(f'    {parent} ||--o{{ {table.name} : "{column}"')
    return "\n".join(lines)


def build_document(tables: dict[str, Table], migration_names: list[str]) -> str:
    relationships = sum(len(t.references) for t in tables.values())
    return (
        "# Entity-relationship diagram\n\n"
        "Generated by `python scripts/generate_er_diagram.py` from the migrations in `backend/db/migrations/` "
        f"({migration_names[0]} to {migration_names[-1]}). Do not edit by hand: change the migrations and "
        "re-run the script. `PK` primary key, `FK` foreign key, `UK` unique.\n\n"
        f"{len(tables)} tables, {relationships} foreign-key relationships.\n\n"
        "```mermaid\n" + render(tables) + "\n```\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate docs/architecture/er-diagram.md from the SQL migrations")
    parser.add_argument("--check", action="store_true", help="fail when docs/architecture/er-diagram.md is out of date")
    args = parser.parse_args()
    files = sorted(MIGRATIONS.glob("*.sql"), key=lambda p: p.name)
    document = build_document(parse([f.read_text(encoding="utf-8") for f in files]), [f.name for f in files])
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != document:
            print("docs/architecture/er-diagram.md is out of date: run python scripts/generate_er_diagram.py", file=sys.stderr)
            return 1
        print("docs/architecture/er-diagram.md is up to date")
        return 0
    OUTPUT.write_text(document, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
