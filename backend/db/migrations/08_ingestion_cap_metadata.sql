BEGIN;

-- Preserve CAP context that is needed for warning display and audit review.
ALTER TABLE external_alerts ADD COLUMN IF NOT EXISTS urgency VARCHAR(20);
ALTER TABLE external_alerts ADD COLUMN IF NOT EXISTS certainty VARCHAR(20);
ALTER TABLE external_alerts ADD COLUMN IF NOT EXISTS language VARCHAR(10);

COMMIT;
