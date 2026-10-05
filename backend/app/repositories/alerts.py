import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Alert, AlertRule, Resource


def rules_for_account(session: Session, owner_id: uuid.UUID, account_id: uuid.UUID
                      ) -> list[AlertRule]:
    """Enabled rules of the owner covering this account (account-wide, per-resource, or global)."""
    resource_ids = select(Resource.id).where(Resource.account_id == account_id)
    return list(session.scalars(
        select(AlertRule).where(
            AlertRule.owner_id == owner_id, AlertRule.is_enabled.is_(True),
            AlertRule.deleted_at.is_(None),
            or_(AlertRule.account_id == account_id,
                AlertRule.resource_id.in_(resource_ids),
                (AlertRule.account_id.is_(None)) & (AlertRule.resource_id.is_(None))))))


def owner_has_rules(session: Session, owner_id: uuid.UUID) -> bool:
    return bool(session.scalar(
        select(func.count()).select_from(AlertRule)
        .where(AlertRule.owner_id == owner_id, AlertRule.deleted_at.is_(None))))


def unresolved(session: Session, rule_id: uuid.UUID) -> dict[uuid.UUID, Alert]:
    rows = session.scalars(select(Alert).where(Alert.rule_id == rule_id,
                                               Alert.state != "resolved"))
    return {a.resource_id: a for a in rows}


def open_alert(session: Session, rule_id: uuid.UUID, resource_id: uuid.UUID, value: float,
               now: datetime) -> Alert:
    alert = Alert(rule_id=rule_id, resource_id=resource_id, state="open", opened_at=now,
                  value_at_open=value)
    session.add(alert)
    return alert


def resolve(alert: Alert, now: datetime) -> None:
    alert.state = "resolved"
    alert.resolved_at = now
