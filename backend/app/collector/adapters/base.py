from datetime import datetime
from typing import Protocol

from app.collector.dto import AccountRef, MetricSampleDTO, ResourceDTO


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
