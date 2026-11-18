-- =====================================================================
-- DRCH - Migration 17: Internal incident notes
--
-- A shared, append-only log for the dispatch team on each incident (for
-- example what was agreed on a phone call), so the next shift can pick up
-- where the last one stopped. Notes are visible to Disaster Management staff
-- only, never to the reporter. There is no edit or delete: a correction is a
-- new note. Each note is also an entry in audit_logs.
-- =====================================================================

CREATE TABLE IF NOT EXISTS incident_notes (
    note_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID        NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    author_id   UUID        NOT NULL REFERENCES users(user_id),
    body        TEXT        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 1000),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incident_notes_incident
    ON incident_notes(incident_id, created_at DESC);
