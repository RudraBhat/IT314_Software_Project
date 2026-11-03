-- =====================================================================
-- Disaster Response Coordination Hub (DRCH) - IT314 Software Engineering
-- Unified Database Seed Data
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. BASELINE ROLES
-- ---------------------------------------------------------------------
INSERT INTO roles (code, description) VALUES
 ('NORMAL_USER',  'Citizen: report incidents, track timeline, donate money, contribute physical aid'),
 ('DISASTER_MGMT','Operational staff: review, verify, triage, dispatch resources, coordinate agencies, publish verified updates'),
 ('APP_MGMT',     'Platform administrator: accounts, RBAC, system config, monitoring, audit, backups, security'),
 ('FIELD_TEAM',   'Field Team Responder: receive assignments, acknowledge, report progress, request backup, complete missions')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------
-- 2. DISASTER RESPONSE AGENCIES
-- ---------------------------------------------------------------------
INSERT INTO agencies (name, agency_type, contact_email, contact_phone, is_active) VALUES
 ('National Disaster Response Force (NDRF)',              'NDRF',      'ops@ndrf.gov.in',               '1078',        TRUE),
 ('State Emergency Operations Centre (SEOC)',              'MUNICIPAL', 'control@seoc.state.gov.in',      '1070',        TRUE),
 ('Fire and Emergency Services Command',                   'FIRE',       'dispatch@fire.gov.in',          '101',         TRUE),
 ('City Police Disaster Incident Cell',                    'POLICE',     'incident@police.gov.in',        '100',         TRUE),
 ('Emergency Medical & Ambulance Network',                 'MEDICAL',    'triage@ems.gov.in',              '108',         TRUE),
 ('Gujarat State Disaster Management Authority (GSDMA)',   'MUNICIPAL', 'control@gsdma.gujarat.gov.in',  '07923259283', TRUE),
 ('NDRF 6th Battalion (Vadodara)',                         'NDRF',      'ops.06bn-ndrf@gov.in',         '02652830491', TRUE),
 ('Gujarat Fire and Emergency Services (Ahmedabad HQ)',    'FIRE',       'firealert@ahmedabadcity.gov.in','101',         TRUE),
 ('Gujarat State Police Emergency Command (Gandhinagar)',  'POLICE',     'control.police@gujarat.gov.in',  '100',         TRUE),
 ('EMRI Green Health Services Gujarat (108 Ambulance)',   'MEDICAL',    'dispatch@108gujarat.org',        '108',         TRUE),
 ('SDRF Gujarat Command (State Disaster Response Force)',  'NDRF',      'sdrf-ops@gujarat.gov.in',        '07923250100', TRUE)
ON CONFLICT (name) DO UPDATE SET is_active = TRUE;

-- ---------------------------------------------------------------------
-- 3. INITIAL BOOTSTRAP USERS & AUTHENTICATION
-- ---------------------------------------------------------------------
-- Admin bootstrap user
INSERT INTO users (user_id, role_id, email, phone, full_name, status)
SELECT 'a0000000-0000-0000-0000-000000000001'::uuid,
       r.role_id,
       'admin@drch.gov.in',
       '+919999999999',
       'System Administrator',
       'ACTIVE'
FROM roles r WHERE r.code = 'APP_MGMT'
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_auth (user_id, password_hash, mfa_enabled)
SELECT u.user_id,
       '$argon2id$v=19$m=65536,t=3,p=4$drch_bootstrap_admin_hash',
       FALSE
FROM users u WHERE u.email = 'admin@drch.gov.in'
ON CONFLICT (user_id) DO NOTHING;

-- Automated Ingestion System user
INSERT INTO users (user_id, role_id, email, phone, full_name, status)
SELECT 'a0000000-0000-0000-0000-000000000002'::uuid,
       r.role_id,
       'ingest-system@drch.gov.in',
       '+910000000000',
       'Automated Ingestion System',
       'ACTIVE'
FROM roles r WHERE r.code = 'APP_MGMT'
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_auth (user_id, password_hash, mfa_enabled)
SELECT u.user_id,
       '$argon2id$v=19$m=65536,t=3,p=4$drch_ingest_system_placeholder',
       FALSE
FROM users u WHERE u.email = 'ingest-system@drch.gov.in'
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. SYSTEM CONFIGURATION
-- ---------------------------------------------------------------------
INSERT INTO system_configs (config_key, value, version, is_active, changed_by)
SELECT 'SCENARIOS_SUPPORTED',
       '{"scenarios": ["CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING"], "max_upload_size_mb": 25, "allowed_evidence_types": ["image/jpeg", "image/png", "video/mp4", "application/pdf"]}'::jsonb,
       1, TRUE, u.user_id
FROM users u WHERE u.email = 'admin@drch.gov.in'
ON CONFLICT (config_key) DO UPDATE SET
       value = EXCLUDED.value,
       updated_at = now();

-- ---------------------------------------------------------------------
-- 5. SAFETY GUIDANCE & STANDARD OPERATING PROCEDURES (NU-FR-08)
-- ---------------------------------------------------------------------
INSERT INTO safety_content (scenario, title, body, status, version, published_at, source) VALUES
 ('CYCLONE', 'Cyclone Safety & Evacuation Advisory',
  'Stay indoors away from windows. Disconnect electrical appliances. Move to designated storm shelters if in low-lying coastal zones.',
  'PUBLISHED', 1, now(), 'GSDMA SOP'),
 ('INDUSTRIAL_FIRE', 'Industrial Chemical & Fire Emergency SOP',
  'Evacuate upwind of smoke plumes. Cover nose and mouth with a damp cloth. Do not use elevators. Await hazardous material fire response.',
  'PUBLISHED', 1, now(), 'Gujarat Fire Services'),
 ('URBAN_FLOODING', 'Urban Flash Flood Response Protocol',
  'Move to higher floors immediately. Do not attempt to walk or drive through moving water. Avoid contact with downed power lines.',
  'PUBLISHED', 1, now(), 'SEOC Emergency Directive')
ON CONFLICT (scenario, title, version) DO NOTHING;

COMMIT;
