-- =====================================================================
-- DRCH - Migration 19: Drop schema objects nothing uses
--
-- A schema review found objects that no application code, script, test or
-- other migration reads or writes. They only cost storage and confuse
-- anyone reading the schema:
--
--   * system_configs - created in 01 and seeded with one
--     'SCENARIOS_SUPPORTED' row, but never read. The supported scenarios
--     come from the scenario_type enum and the code, not this table.
--   * v_incident_summary, v_incident_dashboard, v_dispatch_summary
--     - analytics views from 01 that no query selects from.
--     (v_aid_summary, v_donation_summary and v_resource_availability are
--     used by the DM analytics and aid screens and stay.)
--   * aid_needs.delivery_geom, aid_contributions.pickup_geom,
--     public_updates.affected_area, notifications.sent_at - columns that no
--     code writes, so they are NULL in every row.
--
-- No data of value is lost: the columns were always NULL, and the only
-- system_configs row duplicated values that live in the code. Dropping the
-- table also drops its updated_at trigger. Safe to run more than once.
--
-- Seeds run after all migrations, so the reference seed
-- (seeds/reference/10_reference_data.sql) no longer inserts into
-- system_configs. Databases that already applied that seed never re-run it,
-- so the edit only matters for fresh databases.
-- =====================================================================

DROP VIEW IF EXISTS v_incident_summary;
DROP VIEW IF EXISTS v_incident_dashboard;
DROP VIEW IF EXISTS v_dispatch_summary;

DROP TABLE IF EXISTS system_configs;

ALTER TABLE aid_needs         DROP COLUMN IF EXISTS delivery_geom;
ALTER TABLE aid_contributions DROP COLUMN IF EXISTS pickup_geom;
ALTER TABLE public_updates    DROP COLUMN IF EXISTS affected_area;
ALTER TABLE notifications     DROP COLUMN IF EXISTS sent_at;
