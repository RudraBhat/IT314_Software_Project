"""Phase 5: Automated Testing, Security Hardening & Integration Gate (S1-07, S1-09).

Owned by: Nisarg
Covers:
1. Public API Security & PII Protection (no SUBMITTED/REJECTED leaks, no PII fields).
2. Gujarat Geofencing Precision & PostGIS Boundary Cache.
"""

import pytest

from app.geo import (
    _bbox_check,
    district_for,
    get_boundary_cache_status,
    is_in_gujarat,
    load_boundaries_from_db,
)

# Public API tests live in tests/test_public_api.py (DB-backed, no demo data).

# ═══════════════════════════════════════════════════════════════════════════
# 2. GUJARAT GEOFENCING TESTS (geo.py Precision)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "city,lat,lon",
    [
        ("Ahmedabad", 23.0225, 72.5714),
        ("Surat", 21.1702, 72.8311),
        ("Vadodara", 22.3072, 73.1812),
        ("Rajkot", 22.3039, 70.8022),
        ("Bhuj", 23.2420, 69.6669),
        ("Gandhinagar", 23.2156, 72.6369),
        ("Bhavnagar", 21.7645, 72.1519),
        ("Jamnagar", 22.4707, 70.0577),
    ],
)
def test_geofence_inside_gujarat(city, lat, lon):
    """All major Gujarat cities must pass geofencing."""
    assert is_in_gujarat(lat, lon) is True, f"{city} ({lat}, {lon}) falsely flagged outside Gujarat"


@pytest.mark.parametrize(
    "city,lat,lon",
    [
        ("Mumbai", 19.0760, 72.8777),
        ("Pune", 18.5204, 73.8567),
        ("Delhi", 28.6139, 77.2090),
        ("Jaipur", 26.9124, 75.7873),
        ("Udaipur", 24.5854, 73.7125),
        ("Karachi", 24.8607, 67.0011),
    ],
)
def test_geofence_outside_gujarat(city, lat, lon):
    """External cities across borders must be rejected."""
    assert is_in_gujarat(lat, lon) is False, f"{city} ({lat}, {lon}) falsely flagged inside Gujarat"


def test_fast_bbox_prefilter():
    """Verify bbox prefilter rejects points before expensive raycasting."""
    # Delhi is far outside bbox
    assert _bbox_check(28.6139, 77.2090) is False
    # Mumbai is south of min_lat (20.1)
    assert _bbox_check(19.0760, 72.8777) is False
    # Ahmedabad is inside bbox
    assert _bbox_check(23.0225, 72.5714) is True


def test_district_for_lookup():
    """Verify district resolution for coordinates."""
    assert district_for(23.0225, 72.5714) == "Ahmedabad"
    assert district_for(22.3039, 70.8022) == "Rajkot"
    # External point returns None
    assert district_for(19.0760, 72.8777) is None


def test_boundary_cache_startup_and_telemetry():
    """Verify Option 2: PostGIS boundary cache loads into RAM and tracks telemetry."""
    # Ensure cache telemetry contract is respected
    telemetry = get_boundary_cache_status()
    assert telemetry["state"] == "Gujarat"
    assert telemetry["polygon_vertex_count"] > 10
    assert telemetry["district_centroid_count"] == 33
    assert "min_lat" in telemetry["bbox"]
    assert "max_lat" in telemetry["bbox"]

    # Verify graceful fallback if mock conn has no rows
    class EmptyConn:
        def execute(self, *args, **kwargs):
            class Cursor:
                def fetchone(self):
                    return None
                def fetchall(self):
                    return []
            return Cursor()

    loaded = load_boundaries_from_db(conn=EmptyConn())
    assert loaded is False
    # Cache should remain valid with fallbacks
    assert get_boundary_cache_status()["polygon_vertex_count"] > 10

