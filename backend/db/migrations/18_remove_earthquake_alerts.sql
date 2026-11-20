-- =====================================================================
-- DRCH - Migration 18: Remove stored earthquake alerts
--
-- Earthquake is not a supported scenario (only cyclone, industrial fire and
-- urban flooding are). The SACHET adapter used to store CAP earthquake alerts
-- as event_type 'EARTHQUAKE', and the retired USGS feed did the same; no
-- dispatch, triage or recommendation path can act on them, yet the public
-- alerts API returned them. The adapter now skips them, and this migration
-- deletes the rows already stored. Nothing references external_alerts, and
-- the raw CAP feeds remain the source of record. Safe to run more than once.
-- =====================================================================

DELETE FROM external_alerts
WHERE upper(event_type) IN ('EARTHQUAKE', 'SEISMIC', 'TREMOR');
