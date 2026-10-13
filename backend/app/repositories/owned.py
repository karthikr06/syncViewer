"""Workspace-scoped reads and writes; rows of another workspace behave as missing (404)."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Interval, Select, func, literal, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlertRule,
    CloudAccount,
    Incident,
    MetricDefinition,
    MetricSample,
    Provider,
    Recommendation,
    Resource,
    UptimeRollup,
)

MAX_PAGE_SIZE = 100


def paginate(session: Session, stmt: Select, page: int, page_size: int):
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total, page, page_size


def _sorted(stmt: Select, sort: str | None, allowed: dict, default):
    """sort='name' or '-name'; unknown keys fall back to the default."""
    desc = bool(sort) and sort.startswith("-")
    col = allowed.get((sort or "").lstrip("-"))
    if col is None:
        return stmt.order_by(default)
    return stmt.order_by(col.desc() if desc else col.asc(), default)


# ---- cloud accounts -------------------------------------------------------------------------
def list_accounts(session: Session, owner: uuid.UUID, q: str | None, status: str | None,
                  page: int, page_size: int, sort: str | None):
    stmt = select(CloudAccount).where(CloudAccount.workspace_id == owner,
                                      CloudAccount.deleted_at.is_(None))
    if q:
        stmt = stmt.where(CloudAccount.name.icontains(q, autoescape=True))
    if status:
        stmt = stmt.where(CloudAccount.status == status)
    stmt = _sorted(stmt, sort, {"name": CloudAccount.name, "status": CloudAccount.status,
                                "created_at": CloudAccount.created_at}, CloudAccount.created_at)
    return paginate(session, stmt, page, page_size)


def get_account(session: Session, owner: uuid.UUID, account_id: uuid.UUID) -> CloudAccount | None:
    return session.scalar(select(CloudAccount).where(
        CloudAccount.id == account_id, CloudAccount.workspace_id == owner,
        CloudAccount.deleted_at.is_(None)))


def create_account(session: Session, owner: uuid.UUID, provider_id: int, name: str,
                   external_ref: str, config: dict, credentials_encrypted: bytes | None
                   ) -> CloudAccount:
    account = CloudAccount(workspace_id=owner, provider_id=provider_id, name=name,
                           external_ref=external_ref, config=config,
                           credentials_encrypted=credentials_encrypted)
    session.add(account)
    session.flush()
    return account


def soft_delete_account(session: Session, account: CloudAccount, now: datetime) -> None:
    """Tombstone the account and its resources so deletions propagate through delta sync."""
    account.deleted_at = now
    for res in session.scalars(select(Resource).where(Resource.account_id == account.id,
                                                      Resource.deleted_at.is_(None))):
        res.deleted_at = now


def provider_by_code(session: Session, code: str) -> Provider | None:
    return session.scalar(select(Provider).where(Provider.code == code))


# ---- resources ------------------------------------------------------------------------------
def _owned_resources() -> Select:
    return (select(Resource).join(CloudAccount, CloudAccount.id == Resource.account_id)
            .where(CloudAccount.deleted_at.is_(None), Resource.deleted_at.is_(None)))


def list_resources(session: Session, owner: uuid.UUID, q: str | None, account_id: uuid.UUID | None,
                   power_state: str | None, health_state: str | None, region: str | None,
                   page: int, page_size: int, sort: str | None):
    stmt = _owned_resources().where(CloudAccount.workspace_id == owner)
    if q:
        stmt = stmt.where(Resource.name.icontains(q, autoescape=True)
                          | Resource.external_id.icontains(q, autoescape=True))
    if account_id:
        stmt = stmt.where(Resource.account_id == account_id)
    if power_state:
        stmt = stmt.where(Resource.power_state == power_state)
    if health_state:
        stmt = stmt.where(Resource.health_state == health_state)
    if region:
        stmt = stmt.where(Resource.region == region)
    stmt = _sorted(stmt, sort, {"name": Resource.name, "region": Resource.region,
                                "power_state": Resource.power_state,
                                "size_sku": Resource.size_sku}, Resource.name)
    return paginate(session, stmt, page, page_size)


def get_resource(session: Session, owner: uuid.UUID, resource_id: uuid.UUID) -> Resource | None:
    return session.scalar(_owned_resources().where(CloudAccount.workspace_id == owner,
                                                   Resource.id == resource_id))


def all_resources(session: Session, owner: uuid.UUID) -> list[Resource]:
    return list(session.scalars(_owned_resources().where(CloudAccount.workspace_id == owner)
                                .order_by(Resource.name)))


def find_resource(session: Session, owner: uuid.UUID, key: str) -> Resource | None:
    """Resolve by id, external id or exact name (used by the agent, which sees names)."""
    base = _owned_resources().where(CloudAccount.workspace_id == owner)
    try:
        by_id = session.scalar(base.where(Resource.id == uuid.UUID(key)))
        if by_id:
            return by_id
    except ValueError:
        pass
    return session.scalar(base.where((Resource.external_id == key) | (Resource.name == key)))


def latest_values(session: Session, resource_id: uuid.UUID) -> dict[str, float]:
    rows = session.execute(
        select(MetricDefinition.code, MetricSample.value)
        .join(MetricDefinition, MetricDefinition.id == MetricSample.metric_id)
        .where(MetricSample.resource_id == resource_id)
        .ext(distinct_on(MetricSample.metric_id))
        .order_by(MetricSample.metric_id, MetricSample.ts.desc())).all()
    return {code: value for code, value in rows}


def metric_series(session: Session, resource_id: uuid.UUID, metric_code: str, start: datetime,
                  end: datetime, step_seconds: int) -> list[tuple[datetime, float]]:
    """Average per `step_seconds` bucket (date_bin), oldest first."""
    origin = datetime(2000, 1, 1, tzinfo=start.tzinfo)
    bucket = func.date_bin(literal(timedelta(seconds=step_seconds), Interval), MetricSample.ts,
                           literal(origin))
    rows = session.execute(
        select(bucket.label("b"), func.avg(MetricSample.value))
        .join(MetricDefinition, MetricDefinition.id == MetricSample.metric_id)
        .where(MetricSample.resource_id == resource_id, MetricDefinition.code == metric_code,
               MetricSample.ts >= start, MetricSample.ts < end)
        .group_by(bucket).order_by(bucket)).all()
    return [(b, float(v)) for b, v in rows]


def incidents_for(session: Session, owner: uuid.UUID, resource_id: uuid.UUID,
                  since: datetime) -> list[Incident]:
    return list(session.scalars(
        select(Incident).join(Resource, Resource.id == Incident.resource_id)
        .join(CloudAccount, CloudAccount.id == Resource.account_id)
        .where(CloudAccount.workspace_id == owner, Incident.resource_id == resource_id,
               (Incident.started_at >= since) | Incident.ended_at.is_(None))
        .order_by(Incident.started_at.desc())))


def rollups_for(session: Session, owner: uuid.UUID, resource_ids: list[uuid.UUID],
                since: datetime) -> list[UptimeRollup]:
    return list(session.scalars(
        select(UptimeRollup).join(Resource, Resource.id == UptimeRollup.resource_id)
        .join(CloudAccount, CloudAccount.id == Resource.account_id)
        .where(CloudAccount.workspace_id == owner, UptimeRollup.resource_id.in_(resource_ids),
               UptimeRollup.bucket_start >= since)
        .order_by(UptimeRollup.resource_id, UptimeRollup.bucket_start)))


# ---- alert rules / alerts -------------------------------------------------------------------
def list_rules(session: Session, owner: uuid.UUID, q: str | None, page: int, page_size: int,
               sort: str | None):
    stmt = select(AlertRule).where(AlertRule.workspace_id == owner, AlertRule.deleted_at.is_(None))
    if q:
        stmt = stmt.where(AlertRule.name.icontains(q, autoescape=True))
    stmt = _sorted(stmt, sort, {"name": AlertRule.name, "severity": AlertRule.severity},
                   AlertRule.created_at)
    return paginate(session, stmt, page, page_size)


def get_rule(session: Session, owner: uuid.UUID, rule_id: uuid.UUID) -> AlertRule | None:
    return session.scalar(select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.workspace_id == owner, AlertRule.deleted_at.is_(None)))


def metric_id_by_code(session: Session, code: str) -> int | None:
    return session.scalar(select(MetricDefinition.id).where(MetricDefinition.code == code))


def list_alerts(session: Session, owner: uuid.UUID, state: str | None, page: int,
                page_size: int):
    stmt = (select(Alert).join(AlertRule, AlertRule.id == Alert.rule_id)
            .where(AlertRule.workspace_id == owner))
    if state:
        stmt = stmt.where(Alert.state == state)
    return paginate(session, stmt.order_by(Alert.opened_at.desc()), page, page_size)


def get_alert(session: Session, owner: uuid.UUID, alert_id: int) -> Alert | None:
    return session.scalar(select(Alert).join(AlertRule, AlertRule.id == Alert.rule_id)
                          .where(Alert.id == alert_id, AlertRule.workspace_id == owner))


# ---- recommendations ------------------------------------------------------------------------
def list_recommendations(session: Session, owner: uuid.UUID, status: str | None,
                         category: str | None, severity: str | None, q: str | None, page: int,
                         page_size: int):
    stmt = select(Recommendation).where(Recommendation.workspace_id == owner)
    if status:
        stmt = stmt.where(Recommendation.status == status)
    if category:
        stmt = stmt.where(Recommendation.category == category)
    if severity:
        stmt = stmt.where(Recommendation.severity == severity)
    if q:
        stmt = stmt.where(Recommendation.title.icontains(q, autoescape=True))
    return paginate(session, stmt.order_by(Recommendation.created_at.desc()), page, page_size)


def get_recommendation(session: Session, owner: uuid.UUID, rec_id: int
                       ) -> Recommendation | None:
    return session.scalar(select(Recommendation).where(Recommendation.id == rec_id,
                                                       Recommendation.workspace_id == owner))
