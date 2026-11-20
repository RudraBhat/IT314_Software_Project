-- DEVELOPMENT ONLY: SYNTHETIC sample alerts for trying "related alerts" (docs/architecture/signal-matching.md).
-- Every row is invented, marked is_simulated = TRUE and prefixed "SYNTHETIC SAMPLE"; none is a real post
-- and none contains personal information. Re-runnable: rows are keyed by (source, source_uid).
-- Timestamps are relative to the first time this seed runs.
BEGIN;

INSERT INTO source_signals (source, source_uid, content_text, language, location_text, latitude, longitude,
                            ai_label, ai_confidence, status, is_simulated, raw_payload, created_at)
VALUES
  -- Pair that SHOULD be suggested: ~430 m apart, 30 min apart, same label, different wording.
  ('REPLAY', 'sample-cluster-flood-a1',
   'SYNTHETIC SAMPLE: Water is rising fast on the service road near Adajan Patiya underpass; two-wheelers are stuck.',
   'en', 'Adajan Patiya, Surat', 21.196000, 72.793000, 'URBAN_FLOODING', 0.880, 'PENDING', TRUE,
   '{"dataset": "signal_matching_demo", "synthetic": true}', now() - interval '50 minutes'),
  ('REPLAY', 'sample-cluster-flood-a2',
   'SYNTHETIC SAMPLE: Heavy waterlogging at Adajan Patiya, vehicles stuck in the underpass, road looks flooded.',
   'en', 'Adajan Patiya, Surat', 21.199500, 72.795000, 'URBAN_FLOODING', 0.840, 'PENDING', TRUE,
   '{"dataset": "signal_matching_demo", "synthetic": true}', now() - interval '20 minutes'),
  -- Close and recent but a DIFFERENT event (fire label, unrelated wording): must NOT be suggested.
  ('REPLAY', 'sample-cluster-fire-b1',
   'SYNTHETIC SAMPLE: Smoke rising from a godown behind the textile market, fire brigade not yet seen.',
   'en', 'Textile market, Surat', 21.201000, 72.789000, 'INDUSTRIAL_FIRE', 0.810, 'PENDING', TRUE,
   '{"dataset": "signal_matching_demo", "synthetic": true}', now() - interval '35 minutes'),
  -- Same kind of event but a DIFFERENT place (hundreds of km away): must NOT be suggested.
  ('REPLAY', 'sample-cluster-flood-far',
   'SYNTHETIC SAMPLE: Canal overflowing near the low bridge, water entering nearby lanes.',
   'en', 'Rajkot', 22.303900, 70.802200, 'URBAN_FLOODING', 0.860, 'PENDING', TRUE,
   '{"dataset": "signal_matching_demo", "synthetic": true}', now() - interval '30 minutes'),
  -- No coordinates: never matched automatically; shown to the dispatcher as "location missing".
  ('REPLAY', 'sample-cluster-no-location',
   'SYNTHETIC SAMPLE: Flooding reported around Adajan Patiya but the sender gave no exact location.',
   'en', NULL, NULL, NULL, 'URBAN_FLOODING', 0.700, 'PENDING', TRUE,
   '{"dataset": "signal_matching_demo", "synthetic": true}', now() - interval '25 minutes')
ON CONFLICT (source, source_uid) DO NOTHING;

COMMIT;
