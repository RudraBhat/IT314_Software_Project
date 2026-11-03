-- DEVELOPMENT ONLY: sample teams, campaigns and simulated Gujarat incidents (is_simulated = TRUE).
-- Applied by app.migrate only when APP_ENV=development.
BEGIN;

-- Includes SAMPLE field teams and campaigns: real ones are created in the DM workspace.
-- =====================================================================
-- 6. FIELD RESPONSE TEAMS (TEAM Resources with PostGIS Locations)
--    Owned by: Nisarg (S1-11, Sprint 1)
--    14 teams across 9 Gujarat districts.
--    Standard capability keys agreed with Siddh (Day 1 handoff):
--      boat, water_rescue, flood_rescue, fire, water_tender, hazmat,
--      chemical_foam, gas_leak, medical, ambulance, search_and_rescue,
--      cyclone_response, heavy_extrication, canine_unit, diver_squad,
--      high_rise_rescue, industrial_fire, triage_support, critical_care,
--      smoke_extraction, inflatable_boats, heavy_machinery
-- =====================================================================

-- ── NDRF 6th Battalion (Vadodara) ───────────────────────────────────
-- Team 1: NDRF 601 Urban Search & Rescue — Vadodara
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'NDRF 601 Urban Search & Rescue (Vadodara)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(73.1812, 22.3072), 4326)::geography,
       '{"search_and_rescue": true, "heavy_extrication": true, "boat": true, "canine_unit": true}'::jsonb
FROM agencies a WHERE a.name = 'NDRF 6th Battalion (Vadodara)'
ON CONFLICT DO NOTHING;

-- Team 2: NDRF 602 Flood & Water Rescue — Ahmedabad (Sabarmati riverfront)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'NDRF 602 Flood & Water Rescue Unit (Ahmedabad Sabarmati)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.5714, 23.0225), 4326)::geography,
       '{"boat": true, "water_rescue": true, "flood_rescue": true, "inflatable_boats": true, "diver_squad": true}'::jsonb
FROM agencies a WHERE a.name = 'NDRF 6th Battalion (Vadodara)'
ON CONFLICT DO NOTHING;

-- Team 3: NDRF 603 Cyclone Coastal Rescue — Jamnagar (Saurashtra coast)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'NDRF 603 Cyclone Coastal Rescue Unit (Jamnagar)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(70.0577, 22.4707), 4326)::geography,
       '{"cyclone_response": true, "search_and_rescue": true, "boat": true, "water_rescue": true}'::jsonb
FROM agencies a WHERE a.name = 'NDRF 6th Battalion (Vadodara)'
ON CONFLICT DO NOTHING;

-- ── Gujarat Fire and Emergency Services ─────────────────────────────
-- Team 4: AFES Fire Tender Unit 1 — Ahmedabad (Navrangpura station)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'AFES Fire Tender Unit 1 (Ahmedabad Navrangpura)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.5613, 23.0373), 4326)::geography,
       '{"fire": true, "water_tender": true, "high_rise_rescue": true, "smoke_extraction": true}'::jsonb
FROM agencies a WHERE a.name = 'Gujarat Fire and Emergency Services (Ahmedabad HQ)'
ON CONFLICT DO NOTHING;

-- Team 5: AFES Fire Tender Unit 2 — Ahmedabad (Maninagar station)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'AFES Fire Tender Unit 2 (Ahmedabad Maninagar)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.6042, 22.9784), 4326)::geography,
       '{"fire": true, "water_tender": true, "heavy_extrication": true, "smoke_extraction": true}'::jsonb
FROM agencies a WHERE a.name = 'Gujarat Fire and Emergency Services (Ahmedabad HQ)'
ON CONFLICT DO NOTHING;

-- Team 6: Hazira Hazmat Chemical Team — Surat (Hazira Industrial Zone)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'Surat Hazira Chemical Hazard & Industrial Fire Team',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.6841, 21.1025), 4326)::geography,
       '{"hazmat": true, "chemical_foam": true, "gas_leak": true, "industrial_fire": true, "fire": true}'::jsonb
FROM agencies a WHERE a.name = 'Gujarat Fire and Emergency Services (Ahmedabad HQ)'
ON CONFLICT DO NOTHING;

-- Team 7: Rajkot Fire Quick Reaction — Rajkot (city centre station)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'Rajkot Fire & Rescue Quick Reaction Unit',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(70.8022, 22.3039), 4326)::geography,
       '{"fire": true, "water_tender": true, "high_rise_rescue": true}'::jsonb
FROM agencies a WHERE a.name = 'Gujarat Fire and Emergency Services (Ahmedabad HQ)'
ON CONFLICT DO NOTHING;

-- ── EMRI Green Health Services Gujarat (108 Ambulance) ──────────────
-- Team 8: 108 ALS Ambulance Alpha — Ahmedabad (Civil Hospital campus)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       '108 ALS Disaster Ambulance Alpha (Ahmedabad Civil)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.6042, 23.0525), 4326)::geography,
       '{"medical": true, "ambulance": true, "critical_care": true, "triage_support": true}'::jsonb
FROM agencies a WHERE a.name = 'EMRI Green Health Services Gujarat (108 Ambulance)'
ON CONFLICT DO NOTHING;

-- Team 9: 108 ALS Ambulance Beta — Surat (New Civil Hospital)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       '108 ALS Disaster Ambulance Beta (Surat New Civil)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.8311, 21.1702), 4326)::geography,
       '{"medical": true, "ambulance": true, "emergency_stabilization": true, "triage_support": true}'::jsonb
FROM agencies a WHERE a.name = 'EMRI Green Health Services Gujarat (108 Ambulance)'
ON CONFLICT DO NOTHING;

-- Team 10: 108 Mobile Triage Unit Gamma — Vadodara (SSG Hospital)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       '108 Mobile Triage Unit Gamma (Vadodara SSG)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(73.1812, 22.3072), 4326)::geography,
       '{"medical": true, "ambulance": true, "triage_support": true, "critical_care": true}'::jsonb
FROM agencies a WHERE a.name = 'EMRI Green Health Services Gujarat (108 Ambulance)'
ON CONFLICT DO NOTHING;

-- ── SDRF Gujarat Command ─────────────────────────────────────────────
-- Team 11: SDRF Flood QRT — Rajkot (Aji River zone)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'SDRF Flood Quick Response Team (Rajkot Aji River)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(70.8022, 22.3039), 4326)::geography,
       '{"boat": true, "flood_rescue": true, "water_rescue": true, "diver_squad": true, "inflatable_boats": true}'::jsonb
FROM agencies a WHERE a.name = 'SDRF Gujarat Command (State Disaster Response Force)'
ON CONFLICT DO NOTHING;

-- Team 12: SDRF Cyclone & Hazmat Response — Bhuj, Kutch
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'SDRF Cyclone & Hazmat Response Unit (Bhuj, Kutch)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(69.6669, 23.2420), 4326)::geography,
       '{"cyclone_response": true, "search_and_rescue": true, "heavy_extrication": true, "canine_unit": true, "heavy_machinery": true}'::jsonb
FROM agencies a WHERE a.name = 'SDRF Gujarat Command (State Disaster Response Force)'
ON CONFLICT DO NOTHING;

-- Team 13: SDRF River Rescue & Dive Squad — Gandhinagar (Sabarmati upstream)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'SDRF River Rescue & Dive Squad (Gandhinagar)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.6369, 23.2156), 4326)::geography,
       '{"boat": true, "water_rescue": true, "flood_rescue": true, "diver_squad": true}'::jsonb
FROM agencies a WHERE a.name = 'SDRF Gujarat Command (State Disaster Response Force)'
ON CONFLICT DO NOTHING;

-- Team 14: SDRF Urban SAR & Medical Support — Surat (Diamond Nagar)
INSERT INTO resources (agency_id, type, name, status, quantity_total, quantity_available, current_geom, capability_tags)
SELECT a.agency_id, 'TEAM'::resource_type,
       'SDRF Urban SAR & Medical Support (Surat)',
       'AVAILABLE'::resource_status, 1, 1,
       ST_SetSRID(ST_MakePoint(72.8500, 21.2000), 4326)::geography,
       '{"search_and_rescue": true, "heavy_extrication": true, "medical": true, "triage_support": true}'::jsonb
FROM agencies a WHERE a.name = 'SDRF Gujarat Command (State Disaster Response Force)'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------
-- 7. ACTIVE DONATION CAMPAIGNS
-- ---------------------------------------------------------------------
INSERT INTO donation_campaigns (campaign_id, title, purpose, scenario, target_amount, currency, status)
VALUES
 ('c0000000-0000-0000-0000-000000000001'::uuid,
  'Gujarat Coastal Cyclone Emergency Relief Fund',
  'Providing immediate dry rations, tarpaulins, drinking water, and medical kits to families displaced across Saurashtra coastal belt.',
  'CYCLONE', 10000000.00, 'INR', 'ACTIVE'),
 ('c0000000-0000-0000-0000-000000000002'::uuid,
  'Kutch Cyclone Storm Surge & Coastal Rehabilitation Drive',
  'Deployment of emergency shelter units, high-speed debris clearance, and structural stabilization across coastal villages.',
  'CYCLONE', 15000000.00, 'INR', 'ACTIVE'),
 ('c0000000-0000-0000-0000-000000000003'::uuid,
  'Surat & South Gujarat Flood Resiliency Program',
  'Funding high-capacity dewatering pumps, community kitchen operations, and emergency boat mobilization for low-lying settlements.',
  'URBAN_FLOODING', 5000000.00, 'INR', 'ACTIVE')
ON CONFLICT (campaign_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 8. DEMO INCIDENTS ACROSS GUJARAT
-- ---------------------------------------------------------------------
INSERT INTO incidents (
    incident_id, incident_ref, reporter_id, scenario, description,
    reported_urgency, status, verified_priority, verified_by, verified_at,
    latitude, longitude, geom, address_text, location_source,
    district, is_simulated, source
)
VALUES
 ('b0000000-0000-0000-0000-000000000001'::uuid,
  'INC-2026-000001', 'a0000000-0000-0000-0000-000000000001'::uuid,
  'URBAN_FLOODING',
  'Severe Waterlogging & Submerged Subway in Navrangpura. Continuous downpour caused 4 feet water accumulation near Mithakhali underpass.',
  'HIGH', 'VERIFIED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
  23.0373, 72.5613, ST_SetSRID(ST_MakePoint(72.5613, 23.0373), 4326)::geography,
  'Mithakhali Underpass, Navrangpura, Ahmedabad', 'GPS',
  'Ahmedabad', TRUE, 'CITIZEN'),

 ('b0000000-0000-0000-0000-000000000002'::uuid,
  'INC-2026-000002', 'a0000000-0000-0000-0000-000000000001'::uuid,
  'INDUSTRIAL_FIRE',
  'Chemical Processing Plant Vapor Cloud Fire in Hazira. Storage tank flange rupture resulted in a volatile solvent fire with heavy black smoke plumes.',
  'CRITICAL', 'DISPATCHED', 'CRITICAL', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
  21.1025, 72.6841, ST_SetSRID(ST_MakePoint(72.6841, 21.1025), 4326)::geography,
  'Hazira Industrial Area, Surat', 'GPS',
  'Surat', TRUE, 'CITIZEN'),

 ('b0000000-0000-0000-0000-000000000003'::uuid,
  'INC-2026-000003', 'a0000000-0000-0000-0000-000000000001'::uuid,
  'CYCLONE',
  'Severe Storm Squall & Tree Fall in Anjar. Coastal squall winds resulted in uprooted trees blocking emergency arterial routes.',
  'HIGH', 'VERIFIED', 'HIGH', 'a0000000-0000-0000-0000-000000000001'::uuid, now(),
  23.1139, 70.0278, ST_SetSRID(ST_MakePoint(70.0278, 23.1139), 4326)::geography,
  'Main Bazaar, Anjar, Kutch', 'MAP_PIN',
  'Kutch', TRUE, 'CITIZEN'),

 ('b0000000-0000-0000-0000-000000000004'::uuid,
  'INC-2026-000004', 'a0000000-0000-0000-0000-000000000001'::uuid,
  'CYCLONE',
  'Coastal Surge & Fishing Boat Inundation at Veraval Harbor. High spring tide combined with pre-cyclonic squall breached harbor wall.',
  'MEDIUM', 'SUBMITTED', NULL, NULL, NULL,
  20.9022, 70.3689, ST_SetSRID(ST_MakePoint(70.3689, 20.9022), 4326)::geography,
  'Old Port Jetty, Veraval, Gir Somnath', 'GPS',
  'Gir Somnath', TRUE, 'CITIZEN')
ON CONFLICT (incident_id) DO NOTHING;



-- Keep generated references (incident_ref_seq) after the demo references above.
SELECT setval('incident_ref_seq', GREATEST((SELECT last_value FROM incident_ref_seq), 4), true);

COMMIT;
