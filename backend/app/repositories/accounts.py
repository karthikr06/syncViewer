import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CloudAccount, Provider


@dataclass(frozen=True)
class CollectableAccount:
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_code: str


def list_collectable(session: Session) -> list[CollectableAccount]:
    """Active and errored accounts (errored ones are retried); paused/deleted are skipped."""
    rows = session.execute(
        select(CloudAccount.id, CloudAccount.owner_id, Provider.code)
        .join(Provider, Provider.id == CloudAccount.provider_id)
        .where(CloudAccount.deleted_at.is_(None), CloudAccount.status.in_(("active", "error")),
               Provider.is_enabled.is_(True))
        .order_by(CloudAccount.created_at)
    ).all()
    return [CollectableAccount(*r) for r in rows]


def get(session: Session, account_id: uuid.UUID) -> CloudAccount | None:
    return session.get(CloudAccount, account_id)


def mark_success(session: Session, account: CloudAccount, now: datetime) -> None:
    account.last_collected_at = now
    account.last_error = None
    if account.status == "error":
        account.status = "active"


def mark_error(session: Session, account_id: uuid.UUID, message: str) -> None:
    account = session.get(CloudAccount, account_id)
    if account is not None:
        account.status = "error"
        account.last_error = message[:2000]
