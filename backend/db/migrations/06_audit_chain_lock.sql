-- =====================================================================
-- DRCH - Migration 06: serialise audit hash-chain writers
-- The original trigger read the latest row_hash without a lock, so two
-- concurrent transactions could chain to the same predecessor and fork the
-- chain. A transaction-scoped advisory lock makes inserts strictly ordered.
-- audit_id is re-assigned AFTER the lock is held: the column default is
-- evaluated before BEFORE-INSERT triggers run, so without this a writer could
-- hold a smaller id than a row that was chained earlier, and the id-ordered
-- verification would report a false break. (Unused ids leave harmless gaps.)
-- The hash formula is UNCHANGED, so verify_audit_chain keeps working on
-- existing rows.
-- =====================================================================
BEGIN;

CREATE OR REPLACE FUNCTION fn_audit_log_hash_chain() RETURNS trigger AS $$
DECLARE
    v_prev_hash CHAR(64);
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('drch.audit_logs.chain'));
    NEW.audit_id := nextval(pg_get_serial_sequence('audit_logs', 'audit_id'));
    SELECT row_hash INTO v_prev_hash FROM audit_logs ORDER BY audit_id DESC LIMIT 1;
    NEW.prev_hash := COALESCE(v_prev_hash, repeat('0', 64));
    NEW.row_hash  := encode(
        digest(
            NEW.prev_hash ||
            NEW.occurred_at::text ||
            COALESCE(NEW.actor_id::text, 'SYSTEM') ||
            NEW.action ||
            NEW.entity_type ||
            COALESCE(NEW.entity_id::text, '') ||
            NEW.result::text ||
            COALESCE(NEW.rationale, ''),
            'sha256'
        ),
        'hex'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMIT;
