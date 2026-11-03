# Ingestion sources and access memo

Last reviewed: 2026-11-03

## Selected implementation

| Source | Use | Access/key | Data handling | Reachability |
|---|---|---|---|---|
| SACHET / NDMA CAP RSS | Official disaster warnings. `SACHET_FEED_URL` points to an RSS subscription; each item links to CAP XML. | Public RSS subscription URL; no API key is documented. The subscription URL is configured by the deployment owner and is not committed here. | Follow NDMA's required `ETag` / `If-None-Match` caching and use cached XML on `304`. Parse only Gujarat-relevant items. Preserve source, severity, urgency, certainty, language and effective/expiry times. | Current shell probe could not resolve `sachet.ndma.gov.in`; actual laptop and Render checks remain pending. |
| USGS GeoJSON | Public earthquake catalog filtered to the Gujarat bounding box, then checked against the packaged Gujarat polygon. | Public GET endpoint; no key. | USGS requests source credit. Event data can be revised, so the service is informational and is not an earthquake warning system. | Current shell probe could not resolve `earthquake.usgs.gov`; actual laptop and Render checks remain pending. |
| Team-authored replay (`REPLAY`) | Selected social-style source for development and demonstrations. No third-party posts are copied into the fixture. | Local file; no network or key. | Every row is sanitised and marked simulated. Text is bounded, HTML and links are removed, and no author identity is recorded. | Laptop: available locally. Render: available in the backend image. |
| Bluesky public AppView (candidate only) | Source spike candidate if the team later approves live social ingestion. | Public read endpoints are documented at `public.api.bsky.app`; no token is required for most `GET` requests. | Posts are public but remain user content under Bluesky's terms. Do not persist live posts until the team approves privacy, retention, takedown and terms handling. The current adapter intentionally uses replay instead. | Current shell probe could not resolve `public.api.bsky.app`; actual laptop and Render checks remain pending. |

## Operational checks still owned outside this code change

Siddh needs to provide the SACHET subscription URL and run each configured source once from Render. The feed URL, `INGEST_TOKEN`, `AI_TRIAGE_URL`, and `AI_TRIAGE_TOKEN` are environment configuration only; secret values must stay with Siddh. The current repository does not include a Render session or hosting credentials, so those reachability results and the 24-hour staging soak cannot be claimed here.

## References

- NDMA [SACHET RSS portal](https://sachet.ndma.gov.in/CapFeed) and [CAP XML integration guide](https://sachet.ndma.gov.in/docs/Integration_Guide_For_Agencies.pdf) (requires ETag caching).
- USGS [earthquake GeoJSON feeds](https://earthquake.usgs.gov/earthquakes/feed/v1.0/index.php), [catalog API](https://earthquake.usgs.gov/fdsnws/event/1/swagger.json), and [data licensing](https://www.usgs.gov/faqs/are-usgs-reportspublications-copyrighted).
- Bluesky [public HTTP API reference](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed) and [Terms of Service](https://bsky.social/about/support/tos).
