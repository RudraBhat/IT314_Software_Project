#!/usr/bin/env python3
"""S3-13 query-plan check for the public map and team-recommendation queries.

Runs EXPLAIN (ANALYZE, BUFFERS) on the exact SQL the API executes:
  * GET /api/v1/public/incidents  - no filter, district, scenario and bounding-box variants;
  * GET /api/v1/dm/incidents/{id}/team-recommendations - the PostGIS team ranking query.

EXPLAIN ANALYZE executes the SELECTs; nothing is written. With --synthetic N the script first
inserts N simulated VERIFIED incidents and a matching number of teams inside ONE transaction,
runs ANALYZE so the planner sees realistic statistics, explains, and then ROLLS BACK: the
database is left exactly as it was. --synthetic is refused on non-local databases unless
--force (same guard as scripts/seed_reset.py).

Usage:
    python scripts/explain_queries.py --database-url postgresql://postgres:postgres@localhost:5432/drch_test
    python scripts/explain_queries.py --database-url ... --synthetic 50000 --out explain.md

The report flags sequential scans over incidents/resources and sorts that spill to disk, which
are the only findings that would justify a new index (added by migration, merged by Siddh).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

# The app reads settings at import time; the explain run needs only a database URL.
os.environ.setdefault("JWT_SECRET", "explain-only-" + "x" * 32)

SYNTHETIC_SQL = """
WITH reporter AS (SELECT user_id FROM users ORDER BY created_at LIMIT 1)
INSERT INTO incidents (incident_ref, reporter_id, scenario, description, reported_urgency, status,
                       verified_priority, verified_by, verified_at, latitude, longitude,
                       address_text, district, is_simulated, source)
SELECT 'PERF-' || g || '-' || substr(md5(random()::text), 1, 8),
       reporter.user_id,
       (ARRAY['CYCLONE', 'INDUSTRIAL_FIRE', 'URBAN_FLOODING'])[1 + g %% 3]::scenario_type,
       'Synthetic EXPLAIN row',
       'HIGH'::priority_level,
       (ARRAY['SUBMITTED', 'VERIFIED', 'DISPATCHED', 'RESOLVED', 'NEEDS_INFORMATION', 'REJECTED'])[1 + g %% 6]::incident_status,
       'HIGH'::priority_level,
       reporter.user_id,
       now() - (g || ' minutes')::interval,
       20.2 + random() * 4.3,
       68.5 + random() * 5.8,
       'Synthetic address',
       (ARRAY['Ahmedabad', 'Surat', 'Vadodara', 'Rajkot', 'Kutch', 'Jamnagar'])[1 + g %% 6],
       TRUE,
       'CITIZEN'
FROM generate_series(1, %(n)s) AS g, reporter
"""

SYNTHETIC_TEAMS_SQL = """
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available,
                       current_geom, capability_tags)
SELECT (SELECT agency_id FROM agencies ORDER BY name LIMIT 1), 'TEAM'::resource_type,
       'PERF team ' || g,
       (ARRAY['AVAILABLE', 'AVAILABLE', 'RESERVED', 'MAINTENANCE'])[1 + g %% 4]::resource_status,
       1, (g %% 2),
       ST_SetSRID(ST_MakePoint(68.5 + random() * 5.8, 20.2 + random() * 4.3), 4326)::geography,
       '{"boat": true, "fire": true}'::jsonb
FROM generate_series(1, %(n)s) AS g
"""

_FINDINGS = [
    (re.compile(r"Seq Scan on (incidents|resources)\b"), "sequential scan on a large table"),
    (re.compile(r"Sort Method: external"), "sort spilled to disk"),
]


def _plan(conn: Any, query: Any, params: dict) -> str:
    from psycopg import sql

    explain = sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) ") + (
        query if isinstance(query, sql.Composable) else sql.SQL(query)
    )
    return "\n".join(r[0] for r in conn.execute(explain, params).fetchall())


def explain_all(conn: Any) -> list[tuple[str, str]]:
    from app.routers.public import build_public_incident_query
    from app.services.recommendations import _POSTGIS_RECOMMEND_SQL

    cases: list[tuple[str, Any, dict]] = []
    for label, kwargs in (
        ("public incidents: no filter", {}),
        ("public incidents: district=Surat", {"district": "Surat"}),
        ("public incidents: scenario=cyclone", {"scenario": "cyclone"}),
        ("public incidents: Ahmedabad bbox", {"bbox": "72.45,22.95,72.70,23.10"}),
    ):
        query, params = build_public_incident_query(**kwargs)
        cases.append((label, query, params))
    cases.append(("team recommendations (Ahmedabad point)", _POSTGIS_RECOMMEND_SQL, {"lat": 23.0225, "lon": 72.5714}))
    return [(label, _plan(conn, q, p)) for label, q, p in cases]


def render(results: list[tuple[str, str]], counts: dict[str, int], synthetic: int) -> str:
    out = [
        "# S3-13 EXPLAIN report",
        "",
        f"Rows visible to the planner: incidents={counts['incidents']}, TEAM resources={counts['teams']}"
        + (f" (includes {synthetic} synthetic incidents, rolled back afterwards)" if synthetic else ""),
        "",
    ]
    for label, plan in results:
        exec_ms = re.search(r"Execution Time: ([\d.]+) ms", plan)
        findings = sorted({msg for rx, msg in _FINDINGS if rx.search(plan)})
        out += [
            f"## {label}",
            "",
            f"Execution time: {exec_ms.group(1) if exec_ms else '?'} ms. "
            f"Findings: {', '.join(findings) if findings else 'none'}.",
            "",
            "```",
            plan,
            "```",
            "",
        ]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--synthetic", type=int, default=0, help="Insert N simulated incidents, then roll back")
    parser.add_argument("--force", action="store_true", help="Allow --synthetic on a non-local database")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    os.environ["DATABASE_URL"] = args.database_url

    if args.synthetic:
        from seed_reset import check_safety_guard

        ok, reason = check_safety_guard(args.database_url, force=args.force)
        if not ok:
            sys.exit(f"Refusing --synthetic: {reason}")

    import psycopg

    with psycopg.connect(args.database_url) as conn:  # one transaction, always rolled back
        if args.synthetic:
            conn.execute(SYNTHETIC_SQL, {"n": args.synthetic})
            conn.execute(SYNTHETIC_TEAMS_SQL, {"n": max(50, args.synthetic // 100)})
            conn.execute("ANALYZE incidents")
            conn.execute("ANALYZE resources")
        counts = {
            "incidents": conn.execute("SELECT count(*) FROM incidents").fetchone()[0],
            "teams": conn.execute("SELECT count(*) FROM resources WHERE type = 'TEAM'").fetchone()[0],
        }
        results = explain_all(conn)
        conn.rollback()

    report = render(results, counts, args.synthetic)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8", newline="\n")
        print(f"report written to {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
