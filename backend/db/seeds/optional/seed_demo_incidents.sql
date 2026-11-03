-- =====================================================================
-- DRCH — Demo Incidents Seed (S1-02 support)
-- ~20 additional incidents across Gujarat districts
-- Only CYCLONE, INDUSTRIAL_FIRE, URBAN_FLOODING scenarios (schema enum).
-- All UUIDs explicit; ON CONFLICT DO NOTHING makes this idempotent.
-- reporter_id / verified_by: seeded admin a0000000-0000-0000-0000-000000000001
-- =====================================================================

BEGIN;

INSERT INTO incidents (
    incident_id, incident_ref, reporter_id, scenario, description,
    reported_urgency, status, verified_priority, verified_by, verified_at,
    latitude, longitude, geom, address_text, location_source,
    district, is_simulated, source
)
VALUES

-- ── Ahmedabad ─────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000010'::uuid,
 'INC-2026-000010', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Maninagar SG Highway underpass fully submerged after 6-hour cloudburst. Over 40 vehicles stalled; 3 rescue boats deployed by AMC.',
 'CRITICAL', 'VERIFIED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 23.0009, 72.6017, ST_SetSRID(ST_MakePoint(72.6017, 23.0009), 4326)::geography,
 'SG Highway Underpass near Maninagar, Ahmedabad', 'GPS',
 'Ahmedabad', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000011'::uuid,
 'INC-2026-000011', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'INDUSTRIAL_FIRE',
 'Naroda industrial estate solvent warehouse fire. Three storage units engulfed; HAZCHEM Level-2 declared, 500-metre exclusion zone active.',
 'CRITICAL', 'DISPATCHED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 23.0790, 72.6586, ST_SetSRID(ST_MakePoint(72.6586, 23.0790), 4326)::geography,
 'GIDC Naroda Industrial Estate, Ahmedabad', 'GPS',
 'Ahmedabad', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000012'::uuid,
 'INC-2026-000012', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Vatva APMC market road flooded knee-deep; perishable goods at risk. 200+ shop owners stranded inside the complex.',
 'HIGH', 'SUBMITTED', NULL, NULL, NULL,
 22.9571, 72.6346, ST_SetSRID(ST_MakePoint(72.6346, 22.9571), 4326)::geography,
 'APMC Vatva Market Road, Ahmedabad', 'MAP_PIN',
 'Ahmedabad', TRUE, 'CITIZEN'),

-- ── Surat ─────────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000013'::uuid,
 'INC-2026-000013', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Adajan residential colony inundated. Tapi river tributary overflow reached ground-floor slabs of 12 apartment blocks.',
 'HIGH', 'VERIFIED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 21.1966, 72.8064, ST_SetSRID(ST_MakePoint(72.8064, 21.1966), 4326)::geography,
 'Adajan Patia, Surat', 'GPS',
 'Surat', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000014'::uuid,
 'INC-2026-000014', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'INDUSTRIAL_FIRE',
 'Sachin GIDC textile dyeing unit fire. Azo-dye chemical drums ignited; 8 workers evacuated, two with smoke inhalation.',
 'HIGH', 'RESOLVED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 21.0866, 72.8923, ST_SetSRID(ST_MakePoint(72.8923, 21.0866), 4326)::geography,
 'Sachin GIDC Phase-II, Surat', 'GPS',
 'Surat', FALSE, 'STAFF'),

('b0000000-0000-0000-0000-000000000015'::uuid,
 'INC-2026-000015', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Ring Road Jahangirpura low-lying stretch waterlogged after drain backflow. Traffic diverted via Udhna Magdalla Road.',
 'MEDIUM', 'SUBMITTED', NULL, NULL, NULL,
 21.1702, 72.8311, ST_SetSRID(ST_MakePoint(72.8311, 21.1702), 4326)::geography,
 'Ring Road, Jahangirpura, Surat', 'MAP_PIN',
 'Surat', TRUE, 'CITIZEN'),

-- ── Vadodara ───────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000016'::uuid,
 'INC-2026-000016', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Vishwamitri river banks breached at Gorwa. Floodwaters entered Gorwa-Refinery industrial corridor; pump stations offline.',
 'CRITICAL', 'VERIFIED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.3267, 73.2062, ST_SetSRID(ST_MakePoint(73.2062, 22.3267), 4326)::geography,
 'Gorwa Refinery Road, Vadodara', 'GPS',
 'Vadodara', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000017'::uuid,
 'INC-2026-000017', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'INDUSTRIAL_FIRE',
 'IOCL Koyali refinery flare stack anomaly. Uncontrolled flaring detected at unit-3; safety systems triggered, NDRF standby activated.',
 'CRITICAL', 'DISPATCHED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.3917, 73.1025, ST_SetSRID(ST_MakePoint(73.1025, 22.3917), 4326)::geography,
 'IOCL Koyali Refinery, Vadodara', 'GPS',
 'Vadodara', FALSE, 'STAFF'),

-- ── Rajkot ────────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000018'::uuid,
 'INC-2026-000018', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'CYCLONE',
 'Biparjoy remnant squalls causing structural damage in Rajkot. Tin-roof structures collapsed in Bhaktinagar; power lines down.',
 'HIGH', 'VERIFIED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.3039, 70.8022, ST_SetSRID(ST_MakePoint(70.8022, 22.3039), 4326)::geography,
 'Bhaktinagar Circle, Rajkot', 'GPS',
 'Rajkot', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000019'::uuid,
 'INC-2026-000019', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Aji river overflow flooding Kalavad Road residential zone. 3 societies evacuated; SDRF boat teams navigating narrow lanes.',
 'HIGH', 'DISPATCHED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.3189, 70.7797, ST_SetSRID(ST_MakePoint(70.7797, 22.3189), 4326)::geography,
 'Kalavad Road Society Area, Rajkot', 'MAP_PIN',
 'Rajkot', TRUE, 'CITIZEN'),

-- ── Gandhinagar ───────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000020'::uuid,
 'INC-2026-000020', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Sector-28 stormwater drain overflow. Government quarter basements flooded; PWD teams deployed with dewatering pumps.',
 'MEDIUM', 'VERIFIED', 'MEDIUM', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 23.2156, 72.6369, ST_SetSRID(ST_MakePoint(72.6369, 23.2156), 4326)::geography,
 'Sector 28, Gandhinagar', 'GPS',
 'Gandhinagar', TRUE, 'CITIZEN'),

-- ── Kutch ─────────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000021'::uuid,
 'INC-2026-000021', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'CYCLONE',
 'Mandvi coastal cyclone landfall impact. 60 knot gusts recorded; harbour wall breached, 35 fishing boats reported missing.',
 'CRITICAL', 'VERIFIED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.8333, 69.3500, ST_SetSRID(ST_MakePoint(69.3500, 22.8333), 4326)::geography,
 'Mandvi Beach & Fishing Harbour, Kutch', 'GPS',
 'Kutch', TRUE, 'CITIZEN'),

('b0000000-0000-0000-0000-000000000022'::uuid,
 'INC-2026-000022', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'CYCLONE',
 'Bhuj old city structural damage from cyclone-force winds. 14 heritage-era buildings partially collapsed; 70 families displaced.',
 'HIGH', 'SUBMITTED', NULL, NULL, NULL,
 23.2419, 69.6669, ST_SetSRID(ST_MakePoint(69.6669, 23.2419), 4326)::geography,
 'Bhuj Old City, Kutch', 'MAP_PIN',
 'Kutch', TRUE, 'CITIZEN'),

-- ── Jamnagar ──────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000023'::uuid,
 'INC-2026-000023', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'INDUSTRIAL_FIRE',
 'Reliance Jamnagar refinery tank farm isolation valve fire. Automated suppression activated; external fire brigade requested.',
 'CRITICAL', 'DISPATCHED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.3009, 70.0530, ST_SetSRID(ST_MakePoint(70.0530, 22.3009), 4326)::geography,
 'Reliance Industries Refinery, Jamnagar', 'GPS',
 'Jamnagar', FALSE, 'STAFF'),

('b0000000-0000-0000-0000-000000000024'::uuid,
 'INC-2026-000024', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'CYCLONE',
 'Dwarka temple road cyclone damage. Salt spray and 50 knot winds damaged pilgrim shelters; NH-51 blocked by fallen trees.',
 'MEDIUM', 'VERIFIED', 'MEDIUM', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 22.2442, 68.9685, ST_SetSRID(ST_MakePoint(68.9685, 22.2442), 4326)::geography,
 'Dwarkadhish Temple Road, Dwarka, Jamnagar', 'GPS',
 'Jamnagar', TRUE, 'CITIZEN'),

-- ── Junagadh / Gir Somnath ────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000025'::uuid,
 'INC-2026-000025', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Junagadh Kalwa Chowk market zone flooded post-monsoon surge. Olapad nallah overflowed; ground floors submerged in 2 ft water.',
 'HIGH', 'VERIFIED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 21.5222, 70.4579, ST_SetSRID(ST_MakePoint(70.4579, 21.5222), 4326)::geography,
 'Kalwa Chowk, Junagadh', 'GPS',
 'Junagadh', TRUE, 'CITIZEN'),

-- ── Bharuch ───────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000026'::uuid,
 'INC-2026-000026', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'INDUSTRIAL_FIRE',
 'Dahej petrochemical SEZ ethylene cracker unit fire. Emergency flare activated; Level-3 HAZCHEM declared, 1 km exclusion zone.',
 'CRITICAL', 'VERIFIED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 21.7285, 72.5334, ST_SetSRID(ST_MakePoint(72.5334, 21.7285), 4326)::geography,
 'Dahej SEZ Petrochemical Zone, Bharuch', 'GPS',
 'Bharuch', FALSE, 'STAFF'),

-- ── Anand ─────────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000027'::uuid,
 'INC-2026-000027', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Anand Vidyanagar campus low-lying roads submerged. Charotar canal overflow affecting Vallabh Vidyanagar residential areas.',
 'MEDIUM', 'SUBMITTED', NULL, NULL, NULL,
 22.5645, 72.9289, ST_SetSRID(ST_MakePoint(72.9289, 22.5645), 4326)::geography,
 'Vallabh Vidyanagar Main Road, Anand', 'MAP_PIN',
 'Anand', TRUE, 'CITIZEN'),

-- ── Amreli ────────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000028'::uuid,
 'INC-2026-000028', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'CYCLONE',
 'Amreli Jafrabad coastal cyclone damage. Pre-cyclone high tide caused inundation of salt farm huts; 200 workers evacuated.',
 'HIGH', 'RESOLVED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 20.8605, 71.3758, ST_SetSRID(ST_MakePoint(71.3758, 20.8605), 4326)::geography,
 'Jafrabad Coastline, Amreli', 'GPS',
 'Amreli', TRUE, 'CITIZEN'),

-- ── Mehsana ───────────────────────────────────────────────────────────
('b0000000-0000-0000-0000-000000000029'::uuid,
 'INC-2026-000029', 'a0000000-0000-0000-0000-000000000001'::uuid,
 'URBAN_FLOODING',
 'Mehsana GIDC Phase-1 road submerged. Drainage infrastructure failure caused 2-day waterlogging; 35 units reporting equipment damage.',
 'MEDIUM', 'VERIFIED', 'MEDIUM', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
 23.5880, 72.3693, ST_SetSRID(ST_MakePoint(72.3693, 23.5880), 4326)::geography,
 'GIDC Phase-1, Mehsana', 'GPS',
 'Mehsana', TRUE, 'STAFF')

ON CONFLICT (incident_id) DO NOTHING;

COMMIT;
