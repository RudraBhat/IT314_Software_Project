#!/usr/bin/env python3
"""S3-14 team-recommendation tuning harness.

Ranks the top 3 teams for 10 benchmark Gujarat incidents and prints a Markdown review sheet
that two reviewers fill in (agree / disagree plus a note for each incident).

Team sources:
  * default: the TEAM rows of the demo seed (backend/db/seeds/demo/90_demo_incidents.sql),
    parsed from the SQL so no database is needed;
  * --database-url: the AVAILABLE teams of a live database, read with the same PostGIS query
    the API uses (read-only: a single SELECT, no writes).

Usage:
    python scripts/evaluate_team_recommendations.py
    python scripts/evaluate_team_recommendations.py --out review-sheet.md
    python scripts/evaluate_team_recommendations.py --database-url "$DATABASE_URL"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.recommendations import (  # noqa: E402
    get_required_capabilities,
    get_secondary_capabilities,
    haversine_km,
    recommend_candidate_teams,
)

DEMO_SEED = ROOT / "backend" / "db" / "seeds" / "demo" / "90_demo_incidents.sql"


@dataclass(frozen=True)
class BenchmarkIncident:
    key: str
    title: str
    scenario: str  # cyclone | industrial_fire | urban_flooding
    district: str
    latitude: float
    longitude: float


# Ten incidents across the three supported scenarios and the main Gujarat regions.
BENCHMARK_INCIDENTS: list[BenchmarkIncident] = [
    BenchmarkIncident("F1", "Mithakhali underpass flooded, Navrangpura", "urban_flooding", "Ahmedabad", 23.0373, 72.5613),
    BenchmarkIncident("F2", "Adajan low-lying society flooded", "urban_flooding", "Surat", 21.1959, 72.7933),
    BenchmarkIncident("F3", "Vishwamitri river overflow, Kalaghoda", "urban_flooding", "Vadodara", 22.3119, 73.1723),
    BenchmarkIncident("F4", "Aji river bank flooding, Rajkot east", "urban_flooding", "Rajkot", 22.2900, 70.8100),
    BenchmarkIncident("I1", "Solvent tank fire, Hazira industrial area", "industrial_fire", "Surat", 21.1025, 72.6841),
    BenchmarkIncident("I2", "Chemical unit fire, Naroda GIDC", "industrial_fire", "Ahmedabad", 23.0790, 72.6560),
    BenchmarkIncident("I3", "Reactor fire, Nandesari GIDC", "industrial_fire", "Vadodara", 22.4110, 73.0990),
    BenchmarkIncident("C1", "Tree fall blocking roads, Anjar", "cyclone", "Kutch", 23.1139, 70.0278),
    BenchmarkIncident("C2", "Storm surge at Bedi port", "cyclone", "Jamnagar", 22.5300, 70.0400),
    BenchmarkIncident("C3", "Harbour wall breach, Veraval", "cyclone", "Gir Somnath", 20.9022, 70.3689),
]

_TEAM_INSERT = re.compile(
    r"INSERT INTO resources \(agency_id, type, name, status, quantity_total, quantity_available, "
    r"current_geom, capability_tags\)\s*SELECT a\.agency_id, 'TEAM'::resource_type,\s*"
    r"'(?P<name>[^']+)',\s*'(?P<status>[A-Z_]+)'::resource_status, (?P<total>\d+), (?P<avail>\d+),\s*"
    r"ST_SetSRID\(ST_MakePoint\((?P<lon>[-\d.]+), (?P<lat>[-\d.]+)\), 4326\)::geography,\s*"
    r"'(?P<caps>\{[^']*\})'::jsonb\s*FROM agencies a WHERE a\.name = '(?P<agency>[^']+)'",
)


def load_seed_teams(seed_file: Path = DEMO_SEED) -> list[dict[str, Any]]:
    """Parse TEAM resource rows from the demo seed SQL."""
    teams = []
    for i, m in enumerate(_TEAM_INSERT.finditer(seed_file.read_text(encoding="utf-8")), start=1):
        teams.append({
            "resource_id": f"seed-team-{i:02d}",
            "name": m["name"],
            "agency_id": f"seed-agency-{m['agency']}",
            "agency_name": m["agency"],
            "status": m["status"],
            "quantity_available": int(m["avail"]),
            "capabilities": json.loads(m["caps"]),
            "latitude": float(m["lat"]),
            "longitude": float(m["lon"]),
        })
    if not teams:
        raise RuntimeError(f"no TEAM rows parsed from {seed_file}")
    return teams


class _SeedConnection:
    """Answers the recommendation team query from parsed seed rows (distance computed per call)."""

    def __init__(self, teams: list[dict[str, Any]]):
        self._teams = teams
        self._rows: list[dict[str, Any]] = []

    def execute(self, _query: str, params: dict[str, float]):
        self._rows = sorted(
            (
                {**t, "distance_km": round(haversine_km(params["lat"], params["lon"], t["latitude"], t["longitude"]), 1)}
                for t in self._teams
                if t["status"] == "AVAILABLE" and t["quantity_available"] > 0
            ),
            key=lambda r: r["distance_km"],
        )
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


def rank_benchmark(conn: Any, limit: int = 3) -> list[tuple[BenchmarkIncident, list]]:
    return [
        (inc, recommend_candidate_teams(inc.latitude, inc.longitude, inc.scenario, limit=limit, conn=conn))
        for inc in BENCHMARK_INCIDENTS
    ]


def render_review_sheet(results: list[tuple[BenchmarkIncident, list]], source: str) -> str:
    lines = [
        "# S3-14 Team-recommendation review sheet",
        "",
        f"Team source: {source}. Generated by `scripts/evaluate_team_recommendations.py`.",
        "Each reviewer marks every incident **Agree** or **Disagree** and writes a note when they disagree.",
        "",
        "## Rules in force",
        "",
        "| Scenario | Primary capabilities (10 pts each) | Secondary capabilities (3 pts each) |",
        "| :--- | :--- | :--- |",
    ]
    for scen in ("urban_flooding", "industrial_fire", "cyclone"):
        lines.append(
            f"| `{scen}` | {', '.join(get_required_capabilities(scen))} | {', '.join(get_secondary_capabilities(scen))} |"
        )
    lines += [
        "",
        "Distance penalty 0.05 per km; a team with no primary capability always ranks below every team with one.",
        "",
        "## Top 3 per incident",
        "",
    ]
    for inc, recs in results:
        lines += [
            f"### {inc.key}. {inc.title} ({inc.district}, `{inc.scenario}`)",
            "",
            "| Rank | Team | km | Primary matched | Secondary | Score |",
            "| ---: | :--- | ---: | :--- | :--- | ---: |",
        ]
        if not recs:
            lines.append("| - | No available team | - | - | - | - |")
        for r in recs:
            lines.append(
                f"| {r.rank} | {r.team_name} | {r.distance_km:.1f} | {', '.join(r.capability_match) or '-'} "
                f"| {', '.join(r.secondary_match) or '-'} | {r.score:.2f} |"
            )
        lines += [
            "",
            "| Reviewer | Verdict (Agree / Disagree) | Note |",
            "| :--- | :--- | :--- |",
            "| Reviewer 1: ____________ | | |",
            "| Reviewer 2: ____________ | | |",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", help="Read AVAILABLE teams from this database (read-only)")
    parser.add_argument("--out", type=Path, help="Write the review sheet to this file instead of stdout")
    args = parser.parse_args()

    if args.database_url:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
            conn.read_only = True
            results = rank_benchmark(conn)
        source = "live database (AVAILABLE TEAM resources)"
    else:
        results = rank_benchmark(_SeedConnection(load_seed_teams()))
        source = f"demo seed `{DEMO_SEED.relative_to(ROOT).as_posix()}`"

    sheet = render_review_sheet(results, source)
    if args.out:
        args.out.write_text(sheet + "\n", encoding="utf-8", newline="\n")
        print(f"review sheet written to {args.out}")
    else:
        print(sheet)


if __name__ == "__main__":
    main()
