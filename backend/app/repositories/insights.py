import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlertRule,
    CloudAccount,
    Incident,
    InsightDigest,
    Recommendation,
    Resource,
    UptimeRollup,
)
from app.repositories.owned import paginate


def list_digests(session: Session, owner: uuid.UUID, page: int, page_size: int):
    stmt = (select(InsightDigest).where(InsightDigest.workspace_id == owner)
            .order_by(InsightDigest.period_end.desc()))
    return paginate(session, stmt, page, page_size)


def latest_digest_end(session: Session, owner: uuid.UUID, min_days: float, max_days: float
                      ) -> datetime | None:
    """Newest digest whose period length is within [min_days, max_days]."""
    length_days = func.extract("epoch", InsightDigest.period_end - InsightDigest.period_start
                               ) / 86400
    return session.scalar(
        select(func.max(InsightDigest.period_end)).where(
            InsightDigest.workspace_id == owner, length_days >= min_days, length_days <= max_days))


def add_digest(session: Session, owner: uuid.UUID, start: datetime, end: datetime, md: str,
               generated_by: str = "rules") -> InsightDigest:
    d = InsightDigest(workspace_id=owner, period_start=start, period_end=end, summary_md=md,
                      generated_by=generated_by)
    session.add(d)
    session.flush()
    return d


def workspace_ids_with_accounts(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(CloudAccount.workspace_id).where(
        CloudAccount.deleted_at.is_(None)).distinct()))


@dataclass
class UptimeRow:
    resource_id: uuid.UUID
    name: str
    up: int
    total: int

    @property
    def percent(self) -> float | None:
        return None if self.total == 0 else 100.0 * self.up / self.total


def fleet_uptime(session: Session, owner: uuid.UUID, start: datetime, end: datetime
                 ) -> list[UptimeRow]:
    rows = session.execute(
        select(Resource.id, Resource.name, func.coalesce(func.sum(UptimeRollup.up_samples), 0),
               func.coalesce(func.sum(UptimeRollup.total_samples), 0))
        .join(CloudAccount, CloudAccount.id == Resource.account_id)
        .outerjoin(UptimeRollup, (UptimeRollup.resource_id == Resource.id)
                   & (UptimeRollup.bucket_start >= start) & (UptimeRollup.bucket_start < end))
        .where(CloudAccount.workspace_id == owner, CloudAccount.deleted_at.is_(None),
               Resource.deleted_at.is_(None))
        .group_by(Resource.id, Resource.name).order_by(Resource.name)).all()
    return [UptimeRow(r[0], r[1], int(r[2]), int(r[3])) for r in rows]


def incidents_between(session: Session, owner: uuid.UUID, start: datetime, end: datetime):
    return session.execute(
        select(Incident, Resource.name)
        .join(Resource, Resource.id == Incident.resource_id)
        .join(CloudAccount, CloudAccount.id == Resource.account_id)
        .where(CloudAccount.workspace_id == owner, Incident.started_at >= start,
               Incident.started_at < end)
        .order_by(Incident.started_at.desc())).all()


def open_alert_count(session: Session, owner: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(Alert).join(AlertRule, AlertRule.id == Alert.rule_id)
        .where(AlertRule.workspace_id == owner, Alert.state != "resolved")) or 0


def new_recommendations(session: Session, owner: uuid.UUID, limit: int = 8):
    order = func.array_position(["critical", "warning", "info"], Recommendation.severity)
    return list(session.scalars(
        select(Recommendation).where(Recommendation.workspace_id == owner,
                                     Recommendation.status == "new")
        .order_by(order, Recommendation.created_at.desc()).limit(limit)))
