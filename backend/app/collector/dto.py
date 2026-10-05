from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ResourceDTO:
    external_id: str
    name: str
    type_code: str = "vm"
    region: str | None = None
    size_sku: str | None = None
    power_state: str = "unknown"
    health_state: str = "unknown"
    tags: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricSampleDTO:
    external_id: str
    metric: str
    ts: datetime
    value: float


@dataclass(frozen=True)
class AccountRef:
    """What an adapter needs to know about an account (plain data, no ORM objects)."""

    id: str
    provider: str
    external_ref: str
    config: dict[str, Any]
    credentials: dict[str, Any]
