import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recommendation


def open_by_key(session: Session, workspace_id: uuid.UUID, dedupe_key: str
                ) -> Recommendation | None:
    return session.scalar(select(Recommendation).where(
        Recommendation.workspace_id == workspace_id, Recommendation.dedupe_key == dedupe_key,
        Recommendation.status == "new"))


def recently_dismissed(session: Session, workspace_id: uuid.UUID, dedupe_key: str,
                       since: datetime) -> bool:
    """Advice dismissed within the cooldown (not raised again until it expires)."""
    return session.scalar(select(Recommendation.id).where(
        Recommendation.workspace_id == workspace_id, Recommendation.dedupe_key == dedupe_key,
        Recommendation.status == "dismissed",
        Recommendation.updated_at >= since).limit(1)) is not None


def open_rule_advice(session: Session, workspace_id: uuid.UUID, category: str,
                     resource_ids: list[uuid.UUID]) -> list[Recommendation]:
    return list(session.scalars(select(Recommendation).where(
        Recommendation.workspace_id == workspace_id, Recommendation.status == "new",
        Recommendation.source == "rule", Recommendation.category == category,
        Recommendation.resource_id.in_(resource_ids))))


def add(session: Session, **fields) -> Recommendation:
    rec = Recommendation(**fields)
    session.add(rec)
    return rec


__all__ = ["add", "open_by_key", "open_rule_advice", "recently_dismissed", "timedelta"]
