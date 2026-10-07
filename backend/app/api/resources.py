import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, current_user, not_found
from app.repositories import owned
from app.schemas.entities import (
    IncidentOut,
    MetricPoint,
    MetricSeries,
    Page,
    ResourceDetail,
    ResourceOut,
)
from app.schemas.requests import METRICS

router = APIRouter(prefix="/resources", tags=["resources"])
MAX_POINTS = 5000


@router.get("", response_model=Page[ResourceOut])
def list_resources(q: str | None = None, account_id: uuid.UUID | None = None,
                   power_state: str | None = None, health_state: str | None = None,
                   region: str | None = None, page: int = 1,
                   page_size: int = Query(25, ge=1, le=100), sort: str | None = None,
                   user: CurrentUser = Depends(current_user), db: Session = DB):
    items, total, page, page_size = owned.list_resources(
        db, user.id, q, account_id, power_state, health_state, region, page, page_size, sort)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{resource_id}", response_model=ResourceDetail)
def get_resource(resource_id: uuid.UUID, user: CurrentUser = Depends(current_user),
                 db: Session = DB):
    res = owned.get_resource(db, user.id, resource_id)
    if res is None:
        raise not_found()
    base = ResourceOut.model_validate(res).model_dump()
    return ResourceDetail(**base, latest=owned.latest_values(db, res.id))


@router.get("/{resource_id}/metrics", response_model=MetricSeries)
def get_metrics(resource_id: uuid.UUID, metric: METRICS = "cpu_percent",
                from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                step: int = Query(300, ge=60, le=86400),
                user: CurrentUser = Depends(current_user), db: Session = DB):
    res = owned.get_resource(db, user.id, resource_id)
    if res is None:
        raise not_found()
    end = (to or datetime.now(UTC)).astimezone(UTC)
    start = (from_ or end - timedelta(hours=24)).astimezone(UTC)
    if start >= end:
        raise HTTPException(422, "'from' must be before 'to'")
    if (end - start).total_seconds() / step > MAX_POINTS:
        raise HTTPException(422, "Too many points requested; use a larger step or a shorter range.")
    pts = owned.metric_series(db, res.id, metric, start, end, step)
    return MetricSeries(resource_id=res.id, metric=metric, step_seconds=step,
                        points=[MetricPoint(ts=t, value=v) for t, v in pts])


@router.get("/{resource_id}/incidents", response_model=list[IncidentOut])
def get_incidents(resource_id: uuid.UUID, days: int = Query(14, ge=1, le=90),
                  user: CurrentUser = Depends(current_user), db: Session = DB):
    if owned.get_resource(db, user.id, resource_id) is None:
        raise not_found()
    return owned.incidents_for(db, user.id, resource_id,
                               datetime.now(UTC) - timedelta(days=days))
