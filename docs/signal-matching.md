# Related-signal suggestions

Helps dispatchers notice when several pending signals (ingested messages or social-style alerts) may describe
the same event. It is **advisory and read-only**: it never confirms a disaster, merges signals, creates
incidents or dispatches teams. Promote and dismiss work exactly as before (contract s.4.3, PUBLISHER or
SUPERVISOR required). No trained model, Kafka, MapReduce or vector database is used.

Code: `backend/app/services/signal_matching.py` (rules and scoring), `GET /signals/related` in
`backend/app/routers/dm/signals.py`, migration `10_signal_matching.sql`, panel
`frontend/src/components/dm/RelatedSignalsPanel.tsx` on the existing **Signals** page.

## Matching rules

Two `PENDING` signals are suggested together when **all** of these hold:

1. **Location:** both have exact coordinates and are within **1 km** (PostGIS `ST_DWithin` on `source_signals.geom`).
   District-centroid and unknown-precision points stay visible as candidates but are never grouped by proximity.
2. **Time:** use `source_created_at` when the source provides it; otherwise use `received_at`
   (`source_signals.created_at`) and mark that fallback in the suggestion. Matching timestamps must differ by
   at most **6 hours**.
3. **Evidence** (at least one):
   - the same disaster label (`ai_label`), or
   - similar wording: Jaccard overlap of content words >= **0.25** with at least **2** shared words.
     If both labels are set but **differ**, wording must be much closer (>= **0.5**) and the suggestion carries a warning.

Consequences:

- A signal without coordinates or without an exact location is never matched. It is listed under `unlocated`
  with either missing-location or approximate-location provenance.
- A **missing label** on one side is allowed only if the wording is similar; the suggestion is flagged.
- Nearby and recent alone is not enough, so a fire and a flood on the same street are not suggested.
- Promoted and dismissed signals are ignored.

Wording: lower-case, punctuation removed, English stop-words and short words dropped, light plural/`-ed`/`-ing`
stripping. Gujarati and Hindi words are compared as whole words (a small stop-word list applies); there is no
translation or synonym handling, so a Gujarati and an English message about the same event will not match on
wording (they can still match on label, distance and time).

### Ranking hint

`ranking_score` is 0-100: distance (up to 30, closer is higher) + time gap (up to 20) + wording overlap
(up to 30, full at Jaccard 0.5) + label (+20 same, -10 conflicting, 0 unknown). **It only orders suggestions.
It is not a probability and not proof that two alerts are the same event.**

### Groups (no chaining)

Groups use **complete linkage**: a signal joins a group only if it is a suggested match of *every* member.
So a group's largest pairwise distance is <= 1 km and its matching-time span is <= 6 h; alerts at the edges of a chain
(A near B, B near C, A far from C) are not merged into one group. Each group reports `centre` (mean of member
coordinates), `max_pairwise_distance_m` (its spread) and `time_range` (earliest to latest matching timestamp).
Groups are capped at 10 signals and are suggestions only: nothing is stored.

## Thresholds

All are constants at the top of `backend/app/services/signal_matching.py`; change them there and update this page.

| Constant | Default | Meaning |
|---|---|---|
| `MATCH_RADIUS_M` | 1000 | Maximum distance between two signals (m) |
| `MATCH_WINDOW_HOURS` | 6 | Maximum gap between received times |
| `MIN_TEXT_JACCARD` / `MIN_SHARED_WORDS` | 0.25 / 2 | "Similar wording" |
| `CONFLICT_MIN_TEXT_JACCARD` | 0.5 | Wording needed when labels differ |
| `MAX_GROUP_SIZE` | 10 | Largest suggested group |
| `MAX_CANDIDATE_PAIRS` | 5000 | Safety cap on candidate pairs; response says `truncated: true` if hit |
| `UNLOCATED_LIMIT` | 50 | Missing or approximate-location candidates listed |
| `WEIGHT_*`, `LABEL_CONFLICT_PENALTY` | 30/20/30/20, 10 | Ranking weights |

## API

`GET /api/v1/dm/signals/related` — any signed-in DM staff (same access as `GET /signals`).

Query: `signal_id` (optional; only suggestions involving that signal, which is returned as `signal_a`) and
`limit` (1-500, default 100; limits pairs returned).

All eligible pending signals are searched in one SQL self-join, not only the ones on screen and not one query per
signal. Response (abridged):

```json
{
  "method": "heuristic",
  "advisory": true,
  "requires_human_review": true,
  "note": "Advisory only. ranking_score (0-100) ...",
  "rules": { "radius_m": 1000, "window_hours": 6, "...": "..." },
  "pairs": [
    {
      "signal_a": { "signal_id": "…", "source": "REPLAY", "content_text": "…", "received_at": "2026-11-08T11:10:00Z",
                    "source_created_at": null, "match_time_basis": "received_fallback",
                    "latitude": 21.196, "longitude": 72.793, "location_text": "Adajan Patiya, Surat",
                    "ai_label": "URBAN_FLOODING", "is_simulated": true },
      "signal_b": { "…": "same fields" },
      "distance_m": 440, "minutes_apart": 30, "shared_words": ["adajan", "patiya", "road"],
      "text_similarity": 0.39, "label_agreement": "match",
      "ranking_score": 78.5,
      "reasons": ["440 m apart (limit 1000 m)", "timestamped 30 min apart (limit 360 min)", "same disaster label (URBAN_FLOODING)"],
      "warnings": ["includes simulated data"]
    }
  ],
  "pairs_total": 1,
  "groups": [ { "group_id": "G1", "signal_ids": ["…", "…"], "size": 2, "centre": { "latitude": 21.1977, "longitude": 72.794 },
                "max_pairwise_distance_m": 440, "time_range": { "start": "…", "end": "…", "span_minutes": 30 },
                "top_ranking_score": 78.5 } ],
  "unlocated": [ { "signal_id": "…", "location_missing": false, "location_approximate": true,
                   "note": "Approximate or unverified coordinates are not used for grouping; …" } ],
  "unlocated_total": 1,
  "truncated": false
}
```

`label_agreement` is `match`, `conflict` or `unknown`. `warnings` may say the labels differ, a label is missing, the
wording is not similar, or simulated data is included. Errors use the standard format (401 not signed in, 403 not
DM staff, 422 invalid `limit`/`signal_id`).

## Dispatcher screen

**DM > Signals** (Pending tab) shows a "Possibly related alerts" card: original and related message, source and
received time, location and distance, label, simulated badge, reasons and the ranking hint, plus a "Possibly related"
badge on matching table rows. There are no new action buttons; the dispatcher uses the existing Promote / Dismiss.

## Try it with sample data

`backend/db/seeds/demo/91_demo_signal_clusters.sql` adds five **synthetic** pending signals
(`is_simulated = TRUE`, text starts "SYNTHETIC SAMPLE", invented, no personal data):

| Sample | Expected |
|---|---|
| `sample-cluster-flood-a1` / `-a2` | Suggested as a pair (different wording, ~440 m, 30 min, same label) |
| `sample-cluster-fire-b1` | Close and recent, but a fire with unrelated wording: not suggested |
| `sample-cluster-flood-far` | Flood, but in Rajkot: not suggested |
| `sample-cluster-no-location` | No coordinates: listed as location missing, never matched |

Demo seeds run only when `APP_ENV=development` and only once per database (rows are timestamped when first seeded; the
6-hour window is between the two signals, not relative to now).

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/drch   # PostGIS database
cd backend && uvicorn main:app --reload --port 8000        # applies migration 10 and the demo seed
cd frontend && npm run dev                                   # open /dm/signals as DM staff, "PENDING" tab
```

Or call the API with a DM staff bearer token: `curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/dm/signals/related`.

Tests: `python -m pytest backend/tests/test_signal_matching.py -v` (the pure-rule tests need no database).

## Limitations

- Heuristic only: shared words and a shared label can both be coincidence, and genuine reports can be worded
  very differently. Dispatchers must read the messages.
- Source timestamps can be missing or stale; receipt time is used as a visible fallback in that case.
- Wording is bag-of-words: no translation, spelling correction, synonyms or location-name resolution, so
  English and Gujarati messages about one event do not match on wording. Place names shared by unrelated alerts
  slightly raise wording similarity.
- Labels come from the optional advisory triage service; without it many signals are unlabelled and need
  similar wording to be suggested.
- Fixed radius of 1 km: no adjustment for dense cities versus rural areas, GPS error or reports about a
  large area (e.g. a river).
- Text-only locations can be displayed as district-centroid candidates, but those points are never used for
  proximity matching. Signals without coordinates are not geocoded further; a dispatcher must place them.
- Suggestions are computed on request and not stored; dismissing a suggestion is not recorded (a dismissed or
  promoted signal simply leaves the pending set).
- Scale: one indexed query, measured at about 2 s for 20,000 pending synthetic signals on a development machine;
  candidate pairs are capped at 5000 (`truncated`). Typical queues are far smaller.
