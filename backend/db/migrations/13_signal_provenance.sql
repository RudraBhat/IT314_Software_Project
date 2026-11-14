-- Preserve source time and location precision separately from platform receipt time/coordinates.
BEGIN;

ALTER TABLE source_signals
    ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS location_precision VARCHAR(32) NOT NULL DEFAULT 'EXACT',
    ADD COLUMN IF NOT EXISTS ai_details JSONB,
    ADD COLUMN IF NOT EXISTS ai_triage_attempted_at TIMESTAMPTZ;

-- Keep only the hashed source ID after manual deletion so overlapping polls do not reinsert the post.
CREATE TABLE IF NOT EXISTS deleted_social_signal_ids (
    source      VARCHAR(50) NOT NULL,
    source_uid  VARCHAR(255) NOT NULL,
    deleted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_by  UUID REFERENCES users(user_id) ON DELETE SET NULL,
    PRIMARY KEY (source, source_uid)
);

-- Earlier live text adapters kept the original timestamps and centroid marker in JSONB.
UPDATE source_signals
SET source_created_at = COALESCE(
        CASE WHEN raw_payload->>'created_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
             THEN (raw_payload->>'created_at')::timestamptz END,
        CASE WHEN raw_payload->>'published_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
             THEN (raw_payload->>'published_at')::timestamptz END
    )
WHERE source_created_at IS NULL AND raw_payload IS NOT NULL;

UPDATE source_signals
SET location_precision = CASE LOWER(COALESCE(raw_payload->>'location_precision', ''))
    WHEN 'district_centroid' THEN 'DISTRICT_CENTROID'
    WHEN 'none' THEN 'NONE'
    ELSE location_precision
END
WHERE raw_payload IS NOT NULL
  AND LOWER(COALESCE(raw_payload->>'location_precision', '')) IN ('district_centroid', 'none');

CREATE INDEX IF NOT EXISTS idx_source_signals_pending_match_time
    ON source_signals ((COALESCE(source_created_at, created_at)))
    WHERE status = 'PENDING';

COMMIT;
