# Optional Database Seeds

This directory contains optional supplemental seed data for development and demonstration purposes.

These files are located in `optional/` so that automated test runners (`conftest.py`) and standard seed resets (`scripts/seed_reset.py`), which use a non-recursive `glob("*.sql")` on `backend/db/seeds/`, only apply the minimal baseline seeds (`seed_data.sql`).

---

## 1. `seed_demo_incidents.sql`

- **Purpose**: S1-02 support dataset containing 20 realistic demo incidents spread across 10 Gujarat districts (Ahmedabad, Surat, Vadodara, Rajkot, Gandhinagar, Kutch, Jamnagar, Junagadh, Bharuch, Anand, Amreli, Mehsana).
- **Supported Scenarios**: Uses only schema-supported scenario enum values (`CYCLONE`, `URBAN_FLOODING`, `INDUSTRIAL_FIRE`).
- **Idempotency**: All records use explicit UUIDs with `ON CONFLICT (incident_id) DO NOTHING`.

---

## 2. How to Apply

### Option A: Via Docker / psql (Direct)

```bash
# For development database (drch_db):
docker exec -i drch_postgres psql -U postgres -d drch_db < backend/db/seeds/optional/seed_demo_incidents.sql

# For test database (drch_test):
docker exec -i drch_postgres psql -U postgres -d drch_test < backend/db/seeds/optional/seed_demo_incidents.sql
```

### Option B: Via `scripts/seed_reset.py`

`scripts/seed_reset.py` supports a `--seed-files` CLI argument or the `SEED_FILES` environment variable:

```bash
python scripts/seed_reset.py --seed-files "backend/db/seeds/seed_data.sql,backend/db/seeds/optional/seed_demo_incidents.sql"
```

---

## ⚠️ Warning for Main Suite Integration

Do **not** move `seed_demo_incidents.sql` into the root `backend/db/seeds/` directory without updating the following upstream tests:

1. **`backend/tests/test_seed_reset.py`**:
   `test_seed_reset_lifecycle_and_idempotency` asserts a hardcoded incident count:
   ```python
   assert counts1["incidents"] == 4  # increases to 24 when this seed is applied
   ```
2. **`backend/tests/test_phase5_public_geo_integration.py`**:
   `test_public_api_query_filters` queries a bounding box around South Gujarat (`[20.0, 22.0] x [71.0, 74.0]`) and asserts:
   ```python
   assert inc["district"] == "Surat"
   ```
   Because `seed_demo_incidents.sql` includes incidents in Bharuch (`lat 21.7285, lon 72.5334`) and Amreli (`lat 20.8605, lon 71.3758`) which naturally fall within these coordinates, that assertion will fail unless updated to allow other districts in that bounding box.
