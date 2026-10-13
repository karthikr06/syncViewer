import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, current_user, not_found, require_writer
from app.models import AlertRule
from app.repositories import owned
from app.schemas.entities import AlertOut, AlertRuleOut, Page
from app.schemas.requests import AlertRuleCreate, AlertRuleUpdate

rules = APIRouter(prefix="/alert-rules", tags=["alert rules"])
alerts = APIRouter(prefix="/alerts", tags=["alerts"])


@rules.get("", response_model=Page[AlertRuleOut])
def list_rules(q: str | None = None, page: int = 1, page_size: int = Query(25, ge=1, le=100),
               sort: str | None = None, user: CurrentUser = Depends(current_user),
               db: Session = DB):
    items, total, page, page_size = owned.list_rules(
        db, user.workspace_id, q, page, page_size, sort)
    return Page(items=items, total=total, page=page, page_size=page_size)


@rules.post("", response_model=AlertRuleOut, status_code=201)
def create_rule(body: AlertRuleCreate, user: CurrentUser = Depends(require_writer),
                db: Session = DB):
    if body.account_id and owned.get_account(db, user.workspace_id, body.account_id) is None:
        raise not_found("Cloud account")
    if body.resource_id and owned.get_resource(db, user.workspace_id, body.resource_id) is None:
        raise not_found()
    metric_id = owned.metric_id_by_code(db, body.metric)
    if metric_id is None:
        raise HTTPException(422, "Unknown metric")
    rule = AlertRule(workspace_id=user.workspace_id, name=body.name, account_id=body.account_id,
                     resource_id=body.resource_id, metric_id=metric_id, operator=body.operator,
                     threshold=body.threshold, duration_minutes=body.duration_minutes,
                     severity=body.severity, is_enabled=body.is_enabled)
    db.add(rule)
    db.flush()
    db.refresh(rule)
    return rule


@rules.patch("/{rule_id}", response_model=AlertRuleOut)
def update_rule(rule_id: uuid.UUID, body: AlertRuleUpdate,
                user: CurrentUser = Depends(require_writer), db: Session = DB):
    rule = owned.get_rule(db, user.workspace_id, rule_id)
    if rule is None:
        raise not_found("Alert rule")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.flush()
    return rule


@rules.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, user: CurrentUser = Depends(require_writer),
                db: Session = DB):
    from datetime import UTC, datetime

    rule = owned.get_rule(db, user.workspace_id, rule_id)
    if rule is None:
        raise not_found("Alert rule")
    rule.deleted_at = datetime.now(UTC)


@alerts.get("", response_model=Page[AlertOut])
def list_alerts(state: str | None = None, page: int = 1,
                page_size: int = Query(25, ge=1, le=100),
                user: CurrentUser = Depends(current_user), db: Session = DB):
    items, total, page, page_size = owned.list_alerts(db, user.workspace_id, state, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@alerts.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, user: CurrentUser = Depends(require_writer),
                db: Session = DB):
    alert = owned.get_alert(db, user.workspace_id, alert_id)
    if alert is None:
        raise not_found("Alert")
    if alert.state == "open":
        alert.state = "acknowledged"
        db.flush()
    return alert
