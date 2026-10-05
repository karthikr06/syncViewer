"""Response models. Credentials are never part of any of them."""
import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str


class AccountOut(ORM):
    id: uuid.UUID
    provider_code: str
    name: str
    external_ref: str
    config: dict[str, Any]
    status: str
    last_collected_at: datetime | None
    last_error: str | None
    deleted_at: datetime | None
    created_at: datetime
    version: int


class ResourceOut(ORM):
    id: uuid.UUID
    account_id: uuid.UUID
    external_id: str
    name: str
    region: str | None
    size_sku: str | None
    power_state: str
    health_state: str
    tags: dict[str, Any]
    attributes: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    deleted_at: datetime | None
    version: int


class AlertRuleOut(ORM):
    id: uuid.UUID
    name: str
    account_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    metric: str
    operator: str
    threshold: float
    duration_minutes: int
    severity: str
    is_enabled: bool
    deleted_at: datetime | None
    version: int


class AlertOut(ORM):
    id: int
    rule_id: uuid.UUID
    resource_id: uuid.UUID
    state: str
    opened_at: datetime
    resolved_at: datetime | None
    value_at_open: float | None
    version: int


class RecommendationOut(ORM):
    id: int
    resource_id: uuid.UUID | None
    category: str
    severity: str
    title: str
    detail: str
    evidence: dict[str, Any]
    status: str
    source: str
    created_at: datetime
    updated_at: datetime
    version: int


class DigestOut(ORM):
    id: int
    period_start: datetime
    period_end: datetime
    summary_md: str
    generated_by: str
    created_at: datetime
    version: int


class IncidentOut(ORM):
    id: int
    resource_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    kind: str
    version: int


class RollupOut(ORM):
    resource_id: uuid.UUID
    bucket_start: datetime
    up_samples: int
    total_samples: int
    avg_cpu: float | None
    p95_cpu: float | None
    max_cpu: float | None
    avg_memory: float | None
    max_disk: float | None
    version: int


class UserOut(ORM):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class CollectorRunOut(ORM):
    id: int
    started_at: datetime
    finished_at: datetime | None
    accounts_processed: int
    samples_inserted: int
    errors: int
    error_details: list[Any] | None


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class MetricSeries(BaseModel):
    resource_id: uuid.UUID
    metric: str
    step_seconds: int
    points: list[MetricPoint]


class ResourceDetail(ResourceOut):
    latest: dict[str, float]
