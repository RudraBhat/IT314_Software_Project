-- Relief shelters and medical posts that citizens can find, kept up to date by dispatchers.
-- Public read model: only name, location, capacity, status and a contact number (no personal data).
BEGIN;

CREATE TABLE IF NOT EXISTS shelters (
    shelter_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(160) NOT NULL,
    type              VARCHAR(20)  NOT NULL DEFAULT 'SHELTER'
                      CHECK (type IN ('SHELTER', 'RELIEF_CAMP', 'MEDICAL_POST')),
    address_text      VARCHAR(300) NOT NULL,
    district          VARCHAR(100),
    latitude          DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude         DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    total_capacity    INTEGER CHECK (total_capacity >= 0),
    current_occupancy INTEGER CHECK (current_occupancy >= 0),
    contact_number    VARCHAR(30),
    status            VARCHAR(12)  NOT NULL DEFAULT 'OPERATIONAL'
                      CHECK (status IN ('OPERATIONAL', 'FULL', 'CLOSED')),
    notes             VARCHAR(500),
    is_simulated      BOOLEAN NOT NULL DEFAULT FALSE,
    created_by        UUID REFERENCES users(user_id) ON DELETE SET NULL,
    updated_by        UUID REFERENCES users(user_id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A shelter cannot hold more people than it has room for.
    CONSTRAINT shelters_occupancy_within_capacity
        CHECK (current_occupancy IS NULL OR total_capacity IS NULL OR current_occupancy <= total_capacity)
);

CREATE INDEX IF NOT EXISTS idx_shelters_public ON shelters (status) WHERE status <> 'CLOSED';

COMMIT;
