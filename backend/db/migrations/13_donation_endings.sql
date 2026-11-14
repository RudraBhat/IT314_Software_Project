-- =====================================================================
-- DRCH - Migration 12: server-side donation endings (S3-11)
--
-- A donation that never completes now ends on the server instead of only
-- in the browser: the donor cancels it (ABANDONED), the gateway reports the
-- payment failed (GATEWAY_DECLINED), or nobody pays it in time (EXPIRED).
-- The status stays the existing txn_status FAILED; the reason and time are
-- recorded alongside it. A later verified payment may still confirm it
-- (app/services/donation_endings.py), so the reason is cleared on confirm.
-- Idempotent: safe to re-run.
-- =====================================================================

BEGIN;

ALTER TABLE donations ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(20);
ALTER TABLE donations ADD COLUMN IF NOT EXISTS failed_at      TIMESTAMPTZ;

ALTER TABLE donations DROP CONSTRAINT IF EXISTS chk_donation_failure_reason;
ALTER TABLE donations ADD CONSTRAINT chk_donation_failure_reason CHECK (
    failure_reason IS NULL
    OR (status = 'FAILED' AND failure_reason IN ('ABANDONED', 'GATEWAY_DECLINED', 'EXPIRED'))
);

-- Expiry scans only unpaid orders, oldest first.
CREATE INDEX IF NOT EXISTS idx_donations_pending_created
    ON donations(created_at) WHERE status = 'PENDING';

COMMIT;
