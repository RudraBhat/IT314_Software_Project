#!/usr/bin/env python3
"""Light load test for the public map and report submission (S3-13). Owner: Shlok.

Measures latency percentiles (p50, p95, p99) under a small, fixed concurrency. It is a smoke-level
load check for a free-tier deployment, not a stress test: keep the request count modest.

  python scripts/load_test.py --base-url https://<staging-backend>.onrender.com --requests 200 --concurrency 5
  python scripts/load_test.py --base-url ... --report-submits 20      # also submits reports (STAGING ONLY)
  python scripts/load_test.py --base-url ... --json                    # machine-readable result

The public map run only reads (GET /api/v1/public/incidents). --report-submits registers one throwaway
citizen and creates real SUBMITTED incidents, so run it only against staging, never production.
Record the p95 of the public map run in docs/quality/load-test.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
import uuid

import httpx

PUBLIC_MAP = "/api/v1/public/incidents"


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile of the samples (pct in 0-100). Empty input gives 0."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarise(name: str, latencies_ms: list[float], errors: int, elapsed_s: float) -> dict:
    count = len(latencies_ms) + errors
    return {
        "endpoint": name,
        "requests": count,
        "errors": errors,
        "error_rate": round(errors / count, 4) if count else 0.0,
        "throughput_rps": round(count / elapsed_s, 2) if elapsed_s else 0.0,
        "p50_ms": round(percentile(latencies_ms, 50), 1),
        "p95_ms": round(percentile(latencies_ms, 95), 1),
        "p99_ms": round(percentile(latencies_ms, 99), 1),
        "max_ms": round(max(latencies_ms), 1) if latencies_ms else 0.0,
        "mean_ms": round(statistics.fmean(latencies_ms), 1) if latencies_ms else 0.0,
    }


async def _run(client: httpx.AsyncClient, total: int, concurrency: int, make_request) -> tuple[list[float], int, float]:
    latencies: list[float] = []
    errors = 0
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(i)

    async def worker() -> None:
        nonlocal errors
        while True:
            try:
                i = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            start = time.perf_counter()
            try:
                res = await make_request(client, i)
                ok = res.status_code < 400
            except httpx.HTTPError:
                ok = False
            if ok:
                latencies.append((time.perf_counter() - start) * 1000)
            else:
                errors += 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return latencies, errors, time.perf_counter() - started


async def run(base_url: str, requests: int, concurrency: int, report_submits: int) -> list[dict]:
    results = []
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        # Wake a sleeping free-tier instance first so the cold start is not counted.
        await client.get("/api/v1/health")

        async def public_map(c, _i):
            return await c.get(PUBLIC_MAP)

        lat, err, took = await _run(client, requests, concurrency, public_map)
        results.append(summarise(f"GET {PUBLIC_MAP}", lat, err, took))

        if report_submits:
            email = f"load.{uuid.uuid4().hex[:10]}@example.in"
            reg = await client.post("/api/v1/auth/register",
                                    json={"email": email, "password": "Load-Test-Pass-2026!", "full_name": "Load Test"})
            reg.raise_for_status()
            headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

            async def submit(c, i):
                payload = {
                    "scenario": "urban_flooding",
                    "description": f"LOAD TEST {i}: synthetic report, please reject.",
                    "reported_urgency": "LOW", "people_affected": 1, "location_source": "GPS",
                    "latitude": 23.0225 + i * 0.0001, "longitude": 72.5714,
                }
                return await c.post("/api/v1/incidents", json=payload,
                                    headers={**headers, "Idempotency-Key": f"load-{uuid.uuid4()}"})

            lat, err, took = await _run(client, report_submits, min(concurrency, 2), submit)
            results.append(summarise("POST /api/v1/incidents", lat, err, took))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Light load test for the ResQ public map and report submit")
    parser.add_argument("--base-url", default=(os.getenv("LOADTEST_BASE_URL") or "http://localhost:8000").rstrip("/"))
    parser.add_argument("--requests", type=int, default=200, help="public map requests (default 200)")
    parser.add_argument("--concurrency", type=int, default=5, help="parallel requests (default 5)")
    parser.add_argument("--report-submits", type=int, default=0,
                        help="also submit this many synthetic reports (staging only; default 0)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.report_submits < 0:
        parser.error("--requests and --concurrency must be at least 1, --report-submits at least 0")

    results = asyncio.run(run(args.base_url.rstrip("/"), args.requests, args.concurrency, args.report_submits))
    if args.json:
        print(json.dumps({"base_url": args.base_url, "concurrency": args.concurrency, "results": results}, indent=2))
    else:
        print(f"target {args.base_url}  concurrency {args.concurrency}")
        for r in results:
            print(f"{r['endpoint']:<32} n={r['requests']:<4} errors={r['errors']:<3} "
                  f"p50={r['p50_ms']}ms p95={r['p95_ms']}ms p99={r['p99_ms']}ms max={r['max_ms']}ms "
                  f"rps={r['throughput_rps']}")
    return 1 if any(r["errors"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
