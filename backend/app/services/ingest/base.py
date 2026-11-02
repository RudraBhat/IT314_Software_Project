"""Base interface for external disaster alert ingestion adapters (R-05, D-12)."""

from abc import ABC, abstractmethod
from typing import Any


class Adapter(ABC):
    """Abstract base class for ingestion adapters."""

    name: str

    @abstractmethod
    def fetch(self) -> list[dict[str, Any]]:
        """Fetch and return alerts as standard dictionaries.

        Expected keys per alert:
          - source_uid (str): Unique external alert ID
          - event_type (str): CYCLONE | URBAN_FLOODING | INDUSTRIAL_FIRE | OTHER
          - severity (str): CRITICAL | HIGH | MEDIUM | LOW
          - area_text (str | None): Description of affected area
          - latitude (float | None): Centroid latitude
          - longitude (float | None): Centroid longitude
          - effective_at (datetime | None): Alert start time
          - expires_at (datetime | None): Alert expiration time
          - raw_payload (dict | None): Raw metadata for audit and display
        """
        ...

