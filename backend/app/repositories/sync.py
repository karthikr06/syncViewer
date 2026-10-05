"""Delta-sync reads: rows of an entity with version > cursor, scoped to one owner.

Soft-deleted rows are returned (tombstones) so clients can remove them locally.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlertRule,
    CloudAccount,
    Incident,
    InsightDigest,
    MetricDefinition,
    MetricSample,
    Recommendation,
    Resource,
    UptimeRollup,
)
from app.schemas import entities as out

ROLLUP_WINDOW = timedelta(days=14)


def _owner_accounts(owner: uuid.UUID):
    return select(CloudAccount.id).where(CloudAccount.owner_id == owner)


def _owner_resources(owner: uuid.UUID):
    return select(Resource.id).where(Resource.account_id.in_(_owner_accounts(owner)))


def _owner_rules(owner: uuid.UUID):
    return select(AlertRule.id).where(AlertRule.owner_id == owner)


def _scope(entity: str, owner: uuid.UUID, now: datetime) -> Select:
    if entity == "cloud_accounts":
        return select(CloudAccount).where(CloudAccount.owner_id == owner)
    if entity == "resources":
        return select(Resource).where(Resource.account_id.in_(_owner_accounts(owner)))
    if entity == "alert_rules":
        return select(AlertRule).where(AlertRule.owner_id == owner)
    if entity == "alerts":
        return select(Alert).where(Alert.rule_id.in_(_owner_rules(owner)))
    if entity == "recommendations":
        return select(Recommendation).where(Recommendation.owner_id == owner)
    if entity == "insight_digests":
        return select(InsightDigest).where(InsightDigest.owner_id == owner)
    if entity == "incidents":
        return select(Incident).where(Incident.resource_id.in_(_owner_resources(owner)))
    if entity == "uptime_rollups":
        return select(UptimeRollup).where(
            UptimeRollup.resource_id.in_(_owner_resources(owner)),
            UptimeRollup.bucket_start >= now - ROLLUP_WINDOW)
    raise KeyError(entity)


MODELS = {
    "cloud_accounts": (CloudAccount, out.AccountOut),
    "resources": (Resource, out.ResourceOut),
    "alert_rules": (AlertRule, out.AlertRuleOut),
    "alerts": (Alert, out.AlertOut),
    "recommendations": (Recommendation, out.RecommendationOut),
    "insight_digests": (InsightDigest, out.DigestOut),
    "incidents": (Incident, out.IncidentOut),
    "uptime_rollups": (UptimeRollup, out.RollupOut),
}


def changes(session: Session, owner: uuid.UUID, entity: str, since: int, limit: int,
            now: datetime) -> list:
    model, _ = MODELS[entity]
    stmt = (_scope(entity, owner, now).where(model.version > since)
            .order_by(model.version.asc()).limit(limit))
    return list(session.scalars(stmt).unique().all())


def samples_since(session: Session, owner: uuid.UUID, since: datetime, metrics: list[str],
                  limit: int, step: int = 300):
    """Raw samples; `step` > 300 thins to every step-th second of the 5-minute grid."""
    thin = ([func.mod(func.extract("epoch", MetricSample.ts), step) == 0] if step > 300 else [])
    stmt = (select(MetricSample.resource_id, MetricDefinition.code, MetricSample.ts,
                   MetricSample.value)
            .join(MetricDefinition, MetricDefinition.id == MetricSample.metric_id)
            .where(MetricSample.resource_id.in_(_owner_resources(owner)),
                   MetricSample.ts >= since, MetricDefinition.code.in_(metrics), *thin)
            .order_by(MetricSample.ts.asc(), MetricSample.resource_id).limit(limit))
    return session.execute(stmt).all()
