import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector.dto import ResourceDTO
from app.models import Resource

REFRESH_LAST_SEEN_AFTER = timedelta(hours=6)  # avoids bumping `version` on every cycle
TRACKED = ("name", "region", "size_sku", "power_state", "health_state", "tags", "attributes")


def for_account(session: Session, account_id: uuid.UUID, include_deleted: bool = False
                ) -> list[Resource]:
    stmt = select(Resource).where(Resource.account_id == account_id)
    if not include_deleted:
        stmt = stmt.where(Resource.deleted_at.is_(None))
    return list(session.scalars(stmt.order_by(Resource.name)))


def sync_inventory(session: Session, account_id: uuid.UUID, type_id: int,
                   dtos: list[ResourceDTO], now: datetime) -> list[Resource]:
    """Upsert the provider's inventory; resources that vanished are soft-deleted (tombstones)."""
    existing = {r.external_id: r for r in for_account(session, account_id, include_deleted=True)}
    seen: set[str] = set()
    for dto in dtos:
        seen.add(dto.external_id)
        row = existing.get(dto.external_id)
        if row is None:
            session.add(Resource(
                account_id=account_id, type_id=type_id, external_id=dto.external_id,
                name=dto.name, region=dto.region, size_sku=dto.size_sku,
                power_state=dto.power_state, health_state=dto.health_state, tags=dto.tags,
                attributes=dto.attributes, first_seen_at=now, last_seen_at=now))
            continue
        changed = row.deleted_at is not None or any(
            getattr(row, f) != getattr(dto, f) for f in TRACKED)
        if changed:
            for f in TRACKED:
                setattr(row, f, getattr(dto, f))
            row.deleted_at = None
            row.last_seen_at = now
        elif now - row.last_seen_at > REFRESH_LAST_SEEN_AFTER:
            row.last_seen_at = now
    for ext, row in existing.items():
        if ext not in seen and row.deleted_at is None:
            row.deleted_at = now
    session.flush()
    return for_account(session, account_id)
