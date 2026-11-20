# Load test (S3-13)

Owner: Shlok (script and runs); Nisarg reads EXPLAIN for the same queries and proposes an index only if a
plan shows the need. Script: [`scripts/load_test.py`](../../scripts/load_test.py).

## How to run

```bash
python scripts/load_test.py --base-url https://<staging-backend>.onrender.com --requests 200 --concurrency 5
```

The default run only reads the public map (`GET /api/v1/public/incidents`). `--report-submits N` also registers one
throwaway citizen and submits N synthetic reports: use it on **staging only**, then reject those reports.
The first request wakes a sleeping free-tier instance, so the cold start is not counted.

## Results

| Date (UTC) | Target and build | Endpoint | Requests / concurrency | Errors | p50 | p95 | p99 | Max | Throughput |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-14 | `it314-software-project-backend1.onrender.com`, build `54007f9` | `GET /api/v1/public/incidents` | 200 / 5 | 0 | 475 ms | **633 ms** | 942 ms | 1,094 ms | 9.8 req/s |
| 2026-11-15 | `drch-backend-latest.onrender.com`, build `1fd1a69` | `GET /api/v1/public/incidents` | 200 / 5 | 0 | 615 ms | **1,301 ms** | 1,515 ms | 1,642 ms | 6.7 req/s |
| 2026-11-15 | `drch-backend-latest.onrender.com`, build `1fd1a69` | `POST /api/v1/incidents` | 20 / 2 | 0 | 1,560 ms | **2,861 ms** | 3,363 ms | 3,363 ms | 1.1 req/s |

**Public map p95: 633 ms** (production baseline) / **1,301 ms** (staging); **Report submit p95: 2,861 ms** (staging, D-18 closed).

Notes on the measurement:

- It was taken from a laptop in India against Render's Ohio region and a Neon database in `us-east-2`, so most of
  each request is network round trip; a client in the same region would see far lower numbers.
- The service runs on Render's free plan (shared CPU, one instance). The numbers are a baseline for this setup,
  not a capacity limit.
- Report submission (`--report-submits`) was not run on this backend, because it creates real incidents; run it on
  the staging service once it exists and add a row.

## When to add an index

Only when `EXPLAIN (ANALYZE, BUFFERS)` on the staging database shows a sequential scan on a large table for one of
these queries; see `scripts/explain_queries.py`. Add it in a new migration and re-run this test to compare p95.
