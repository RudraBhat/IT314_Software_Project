-- =====================================================================
-- DRCH - Migration 05: Citizen incident flow support
--   * incident_ref_seq: source of INC-YYYY-NNNNNN references
-- Idempotent. Do not edit migrations 01-04 (already applied in deployed DBs).
-- =====================================================================
BEGIN;

CREATE SEQUENCE IF NOT EXISTS incident_ref_seq;

-- Continue after the highest numeric suffix already present (seed rows use INC-2026-00000N).
SELECT setval(
    'incident_ref_seq',
    GREATEST(
        (SELECT COALESCE(MAX(NULLIF(regexp_replace(incident_ref, '^.*-', ''), '')::bigint), 0)
           FROM incidents WHERE incident_ref ~ '^INC-[0-9]{4}-[0-9]+$'),
        1
    ),
    (SELECT EXISTS (SELECT 1 FROM incidents WHERE incident_ref ~ '^INC-[0-9]{4}-[0-9]+$'))
);

COMMIT;
