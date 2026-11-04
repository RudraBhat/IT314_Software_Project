# Ingestion sources and access memo

Last reviewed: 2026-11-04

## Selected implementation

| Source | Use | Access/key | Data handling | Reachability |
|---|---|---|---|---|
| SACHET / NDMA CAP RSS | Official disaster warnings. `SACHET_FEED_URL` points to an RSS subscription; each item links to CAP XML. | Public RSS subscription URL; no API key is documented. The subscription URL is configured by the deployment owner and is not committed here. | Follow NDMA's required `ETag` / `If-None-Match` caching and use cached XML on `304`. Parse only Gujarat-relevant items. Preserve source, severity, urgency, certainty, language and effective/expiry times. | Laptop: SACHET portal root returned HTTP 200 on 2026-11-04. The configured CAP subscription URL is still missing, so feed parsing/reachability is unverified. Render check pending. |
| USGS GeoJSON | Public earthquake catalog filtered to the Gujarat bounding box, then checked against the packaged Gujarat polygon. | Public GET endpoint; no key. | USGS requests source credit. Event data can be revised, so the service is informational and is not an earthquake warning system. | Laptop: GeoJSON query returned HTTP 200 on 2026-11-04; the Gujarat/magnitude-filtered one-record probe returned zero events. Render check pending. |
| Team-authored replay (`REPLAY`) | Selected social-style source for development and demonstrations. No third-party posts are copied into the fixture. | Local file; no network or key. | Every row is sanitised and marked simulated. Text is bounded, HTML and links are removed, and no author identity is recorded. | Laptop: available locally. Render: available in the backend image. |
| Bluesky public AppView (candidate only) | Source spike candidate if the team later approves live social ingestion. | Public read endpoints are documented at `public.api.bsky.app`; no token is required for most `GET` requests. | Posts are public but remain user content under Bluesky's terms. Do not persist live posts until the team approves privacy, retention, takedown and terms handling. The current adapter intentionally uses replay instead. | Laptop: a public search request returned HTTP 403 on 2026-11-04; this environment-level result does not establish whether the API is generally unavailable. Render check and source approval remain pending. |

## Operational checks still owned outside this code change

Siddh needs to provide the SACHET subscription URL and run each configured source once from Render. The feed URL, `INGEST_TOKEN`, `AI_TRIAGE_URL`, and `AI_TRIAGE_TOKEN` are environment configuration only; secret values must stay with Siddh. The current repository does not include a Render session or hosting credentials, so those reachability results and the 24-hour staging soak cannot be claimed here.

## Polling, CAP handling and source boundaries

- The backend polls at `INGEST_INTERVAL_SECONDS` (600 seconds by default). This is a ten-minute polling target, not a sub-minute delivery guarantee; a sleeping host or an unavailable source can extend the delay.
- NDMA's CAP guide requires clients to send `If-None-Match` after the first successful CAP XML fetch and reuse the cached XML when the server answers `304`. The SACHET adapter follows that flow. Its ETag and XML cache is process-local, so the first request after a restart is an unconditional fetch.
- CAP permits multiple language-specific `<info>` blocks and defines multiple `<area>` shapes as a union. The adapter checks circle extents (including circles whose centers lie outside Gujarat), polygon vertices/centroids, and area descriptions for Gujarat relevance; it prefers a relevant English block when available, and otherwise retains the first relevant block's language. It keeps the alert as one row per CAP identifier.
- The USGS adapter uses a GeoJSON catalog query narrowed to the Gujarat bounding box and magnitude threshold, then checks results against the Gujarat polygon. USGS documents GeoJSON for programmatic use and the FDSN service for custom location and magnitude queries. Catalog events can be revised; ingestion updates the existing row by `(source, source_uid)` instead of creating duplicates.
- `REPLAY` is the only social-style signal source currently enabled. Its posts are team-authored, simulated, stripped of HTML and links, length-bounded, language-detected, and stored without author identity. No live social posts, 112 call records or drone imagery are currently ingested by this adapter set. A real social source stays out of persistence until the team approves its collection, retention, deletion/takedown and operational-use rules.
- Alerts and social signals remain separate from incidents. Ingestion does not verify or dispatch an incident; a dispatcher must review a signal before promoting it.

## References

- NDMA [SACHET RSS portal](https://sachet.ndma.gov.in/CapFeed) and [CAP XML integration guide](https://sachet.ndma.gov.in/docs/Integration_Guide_For_Agencies.pdf) (requires ETag caching).
- OASIS [Common Alerting Protocol 1.2](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html) (multiple `<info>` and `<area>` elements are valid).
- USGS [earthquake GeoJSON feeds](https://earthquake.usgs.gov/earthquakes/feed/v1.0/index.php), [catalog API](https://earthquake.usgs.gov/fdsnws/event/1/swagger.json), and [data licensing](https://www.usgs.gov/faqs/are-usgs-reportspublications-copyrighted).
- Bluesky [public HTTP API reference](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed), [privacy policy](https://bsky.social/about/support/privacy-policy), and [Terms of Service](https://bsky.social/about/support/tos).
