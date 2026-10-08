from datetime import datetime
from typing import Protocol

from app.collector.dto import AccountRef, MetricSampleDTO, ResourceDTO


class ActionRejected(Exception):
    """The provider refused the action (e.g. starting a VM that is already running)."""


class ProviderAdapter(Protocol):
    """Adapters return plain DTOs, never SDK objects."""

    def list_resources(self, account: AccountRef) -> list[ResourceDTO]: ...

    def fetch_metrics(
        self,
        account: AccountRef,
        resources: list[ResourceDTO],
        since: datetime,
        until: datetime,
    ) -> list[MetricSampleDTO]: ...

    def perform_action(self, account: AccountRef, external_id: str, action: str) -> str:
        """Start, stop, restart or deallocate a VM; returns its new power state."""
        ...
