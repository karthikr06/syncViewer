import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Incident


def in_scope(session: Session, resource_ids: list[uuid.UUID], since: datetime) -> list[Incident]:
    """Incidents that started at/after `since` plus any still open."""
    if not resource_ids:
        return []
    return list(session.scalars(
        select(Incident).where(
            Incident.resource_id.in_(resource_ids),
            (Incident.started_at >= since) | Incident.ended_at.is_(None))))


def add(session: Session, resource_id: uuid.UUID, started_at: datetime, ended_at: datetime | None,
        kind: str = "outage") -> Incident:
    inc = Incident(resource_id=resource_id, started_at=started_at, ended_at=ended_at, kind=kind)
    session.add(inc)
    return inc
