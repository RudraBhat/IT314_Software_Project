# ==============================================================================
# Disaster Response Coordination Hub (DRCH) - Developer Tasks
# ==============================================================================

# Seed files to apply during seed-reset (space-separated list). Leave empty to use the default
# set (backend/db/seeds/reference + demo); set it to override, e.g. SEED_FILES="path/a.sql path/b.sql".
SEED_FILES ?=

# Force override flag (default 0; set FORCE=1 to allow cloud/staging database resets)
FORCE ?= 0

.PHONY: help test migrate seed-reset smoke sync-geo

help:
	@echo "Disaster Response Coordination Hub (DRCH) - Commands:"
	@echo ""
	@echo "  make help        Show this help message"
	@echo "  make test        Run the backend pytest test suite"
	@echo "  make migrate     Run database schema migrations"
	@echo "  make seed-reset  Safely reset tables and restore baseline seed data"
	@echo "                   Seed files: $(if $(SEED_FILES),$(SEED_FILES),default reference + demo)"
	@echo "                   Safety guard: refuses cloud databases unless FORCE=1"
	@echo "                   Prints post-reset counts: users, incidents, resources, campaigns"
	@echo "  make smoke       Run the DRCH core loop smoke tests"
	@echo "  make sync-geo    Synchronize Gujarat administrative boundaries from GeoJSON"

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
