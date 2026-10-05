from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MetricDefinition, Provider, ResourceType


def metric_ids(session: Session) -> dict[str, int]:
    return {m.code: m.id for m in session.scalars(select(MetricDefinition))}


def resource_type_id(session: Session, provider_code: str, type_code: str) -> int | None:
    return session.scalar(
        select(ResourceType.id)
        .join(Provider, Provider.id == ResourceType.provider_id)
        .where(Provider.code == provider_code, ResourceType.code == type_code)
    )
