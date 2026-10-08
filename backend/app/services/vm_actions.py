"""Power actions on VMs (start, stop, restart, deallocate) through the provider adapter.

Every attempt is recorded in vm_actions. On success the resource's power state is updated at once
(its version bumps, so every member's browser picks it up on the next sync); the next collector
cycle confirms it from the provider.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector.adapters import ActionRejected, ProviderAdapter
from app.collector.adapters.mock import HEALTH_BY_POWER
from app.collector.cycle import account_ref
from app.core.config import Settings
from app.models import CloudAccount, Recommendation, Resource, User, VmAction

OFF = ("stopped", "deallocated")
ALLOWED = {  # action -> power states it can be applied to
    "start": OFF,
    "stop": ("running",),
    "restart": ("running",),
    "deallocate": ("running", "stopped"),
}


class ActionNotAllowed(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


def perform(session: Session, settings: Settings, adapter: ProviderAdapter, resource: Resource,
            account: CloudAccount, action: str, actor: uuid.UUID,
            recommendation: Recommendation | None = None) -> VmAction:
    current = resource.power_state
    if current not in ALLOWED[action]:
        raise ActionNotAllowed(f"Cannot {action} a VM that is {current}.")
    record = VmAction(resource_id=resource.id, requested_by=actor, action=action,
                      from_state=current)
    try:
        new_state = adapter.perform_action(account_ref(account, account.provider_code, settings),
                                           resource.external_id, action)
    except NotImplementedError as exc:
        raise ProviderUnavailable("VM actions are not available for this provider yet.") from exc
    except ActionRejected as exc:
        record.status, record.error = "failed", str(exc)[:500]
    except Exception as exc:  # noqa: BLE001 - provider unreachable: keep a record, report it
        record.status, record.error = "failed", f"provider error: {type(exc).__name__}"
    else:
        record.status, record.to_state = "succeeded", new_state
        resource.power_state = new_state
        resource.health_state = HEALTH_BY_POWER.get(new_state, "unknown")
        if recommendation is not None and recommendation.resource_id == resource.id:
            recommendation.status = "done"
    session.add(record)
    session.flush()
    return record


def history(session: Session, resource_id: uuid.UUID, limit: int = 20) -> list[tuple]:
    return list(session.execute(
        select(VmAction, User.email)
        .outerjoin(User, User.id == VmAction.requested_by)
        .where(VmAction.resource_id == resource_id)
        .order_by(VmAction.requested_at.desc(), VmAction.id.desc())
        .limit(limit)))
