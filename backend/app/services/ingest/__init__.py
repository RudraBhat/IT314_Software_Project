"""Disaster alert ingestion service adapters (R-05, D-12)."""

from app.services.ingest.base import Adapter
from app.services.ingest.sachet import SachetAdapter

__all__ = ["Adapter", "SachetAdapter"]

