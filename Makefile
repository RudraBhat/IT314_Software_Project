# ==============================================================================
# Disaster Response Coordination Hub (DRCH) - Developer Tasks
# ==============================================================================

# Seed files to apply during seed-reset (space-separated list).
# To point to Siddh's Gujarat-specific seed, edit this single variable:
SEED_FILES ?= backend/db/seeds/seed_data.sql

# Force override flag (default 0; set FORCE=1 to allow cloud/staging database resets)
FORCE ?= 0

.PHONY: help test migrate seed-reset smoke sync-geo sync-env

help:
	@echo "Disaster Response Coordination Hub (DRCH) - Commands:"
	@echo ""
	@echo "  make help        Show this help message"
	@echo "  make sync-env    Synchronize environment variables from env/ folder"
	@echo "  make test        Run the backend pytest test suite"
	@echo "  make migrate     Run database schema migrations"
	@echo "  make seed-reset  Safely reset tables and restore baseline seed data"
	@echo "                   Active seed file: $(SEED_FILES)"
	@echo "                   Safety guard: refuses cloud databases unless FORCE=1"
	@echo "                   Prints post-reset counts: users, incidents, resources, campaigns"
	@echo "  make smoke       Run the DRCH core loop smoke tests"
	@echo "  make sync-geo    Synchronize Gujarat administrative boundaries from GeoJSON"

sync-env:
	python scripts/sync_env.py

test:
	cd backend && python -m pytest tests/ -v

migrate:
	cd backend && python -m app.migrate

seed-reset:
	@SEED_FILES="$(SEED_FILES)" FORCE="$(FORCE)" python scripts/seed_reset.py

smoke:
	python scripts/smoke.py

sync-geo:
	python scripts/sync_boundaries.py
