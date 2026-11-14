-- =====================================================================
-- DRCH - Migration 11: payment webhook event log (issue #102)
--
-- POST /api/v1/payments/webhook/{gateway} stores every verified event id
-- here before acting on it. The primary key makes replays and concurrent
-- duplicate deliveries no-ops, so a donation is confirmed at most once.
-- Idempotent: safe to re-run. Does not change any existing table.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS payment_webhook_events (
    gateway_name  VARCHAR(50)  NOT NULL,
    event_id      VARCHAR(200) NOT NULL,
    event_type    VARCHAR(100) NOT NULL,
    donation_id   UUID REFERENCES donations(donation_id) ON DELETE SET NULL,
    outcome       VARCHAR(40)  NOT NULL,
    received_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (gateway_name, event_id)
);

CREATE INDEX IF NOT EXISTS idx_payment_webhook_events_donation
    ON payment_webhook_events(donation_id);

COMMIT;
