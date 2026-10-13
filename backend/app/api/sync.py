from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, current_user
from app.repositories import sync as repo

router = APIRouter(prefix="/sync", tags=["sync"])

Entity = Literal["cloud_accounts", "resources", "alert_rules", "alerts", "recommendations",
                 "insight_digests", "incidents", "uptime_rollups"]
SAMPLE_METRICS = ["availability", "cpu_percent", "memory_percent", "disk_used_percent"]
MAX_WINDOW_HOURS = 48


def _z(ts: datetime) -> str:
    """UTC ISO-8601 with a 'Z' suffix (a '+' would need URL-escaping when sent back)."""
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _page(db: Session, owner, entity: str, since: int, limit: int, now: datetime) -> dict:
    model, schema = repo.MODELS[entity]
    rows = repo.changes(db, owner, entity, since, limit, now)
    return {
        "entity": entity,
        "rows": [schema.model_validate(r).model_dump(mode="json") for r in rows],
        "next_since": max((r.version for r in rows), default=since),
        "has_more": len(rows) == limit,
    }


@router.get("/changes")
def changes(entity: Entity, since: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000),
            user: CurrentUser = Depends(current_user), db: Session = DB):
    """Rows with version > since, oldest first, tombstones included."""
    now = datetime.now(UTC)
    return {**_page(db, user.workspace_id, entity, since, limit, now),
            "server_time": now.isoformat()}


@router.get("/bootstrap")
def bootstrap(limit: int = Query(500, ge=1, le=1000), user: CurrentUser = Depends(current_user),
              db: Session = DB):
    """First page of every entity in one round trip; clients continue with /sync/changes."""
    now = datetime.now(UTC)
    return {
        "server_time": now.isoformat(),
        "me": {"id": str(user.id), "email": user.email, "role": user.role,
               "workspace": {"id": str(user.workspace_id), "name": user.workspace_name}},
        "entities": {e: _page(db, user.workspace_id, e, 0, limit, now) for e in repo.MODELS},
    }


@router.get("/metrics")
def metrics(since: datetime | None = None, window: int = Query(24, ge=1, le=MAX_WINDOW_HOURS),
            step: int = Query(300, ge=300, le=3600), limit: int = Query(20000, ge=1, le=50000),
            user: CurrentUser = Depends(current_user), db: Session = DB):
    """Recent samples; `since` is inclusive, otherwise the last `window` hours."""
    now = datetime.now(UTC)
    floor = now - timedelta(hours=window)
    start = max(since.astimezone(UTC), floor) if since else floor
    if start > now:
        raise HTTPException(422, "'since' is in the future")
    rows = repo.samples_since(db, user.workspace_id, start, SAMPLE_METRICS, limit, step)
    return {
        "rows": [{"resource_id": str(r), "metric": m, "ts": _z(t), "value": v}
                 for r, m, t, v in rows],
        "next_since": _z(rows[-1][2]) if rows else None,
        "has_more": len(rows) == limit,
        "server_time": now.isoformat(),
    }
