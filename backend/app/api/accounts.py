import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    DB,
    CurrentUser,
    current_user,
    get_settings,
    not_found,
    rate_limited,
    require_writer,
)
from app.collector.cycle import process_account
from app.collector.dto import AccountRef
from app.core.config import Settings
from app.core.crypto import encrypt_credentials
from app.repositories import lookups, owned
from app.repositories import resources as resource_repo
from app.schemas.entities import AccountOut, Page
from app.schemas.requests import AccountCreate, AccountUpdate

log = logging.getLogger("api.accounts")
router = APIRouter(prefix="/cloud-accounts", tags=["cloud accounts"])


@router.get("", response_model=Page[AccountOut])
def list_accounts(q: str | None = None, status: str | None = None, page: int = 1,
                  page_size: int = Query(25, ge=1, le=100), sort: str | None = None,
                  user: CurrentUser = Depends(current_user), db: Session = DB):
    items, total, page, page_size = owned.list_accounts(db, user.id, q, status, page, page_size,
                                                        sort)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, user: CurrentUser = Depends(current_user),
                db: Session = DB):
    account = owned.get_account(db, user.id, account_id)
    if account is None:
        raise not_found("Cloud account")
    return account


@router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountCreate, request: Request,
                   user: CurrentUser = Depends(require_writer), db: Session = DB,
                   settings: Settings = Depends(get_settings)):
    """One transaction: the account plus its first resource discovery. If discovery fails the
    account is not created."""
    provider = owned.provider_by_code(db, body.provider)
    if provider is None or not provider.is_enabled:
        raise HTTPException(400, f"Provider '{body.provider}' is not available.")
    creds = (encrypt_credentials(settings.credential_encryption_key, body.credentials)
             if body.credentials else None)
    try:
        account = owned.create_account(db, user.id, provider.id, body.name, body.external_ref,
                                       body.config, creds)
    except IntegrityError as exc:
        raise HTTPException(409, "You already added this account.") from exc

    adapter = request.app.state.adapter_factory(provider.code)
    ref = AccountRef(str(account.id), provider.code, account.external_ref, dict(account.config),
                     dict(body.credentials or {}))
    type_id = lookups.resource_type_id(db, provider.code, "vm")
    try:
        dtos = adapter.list_resources(ref)
    except NotImplementedError as exc:
        raise HTTPException(400, f"The {provider.code} integration is not available yet.") from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("discovery failed for new account: %s", type(exc).__name__)
        raise HTTPException(502, "Could not reach the cloud provider. Check the account "
                                 "details and try again.") from exc
    resource_repo.sync_inventory(db, account.id, type_id, dtos, datetime.now(UTC))
    return account


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: uuid.UUID, body: AccountUpdate,
                   user: CurrentUser = Depends(require_writer), db: Session = DB,
                   settings: Settings = Depends(get_settings)):
    account = owned.get_account(db, user.id, account_id)
    if account is None:
        raise not_found("Cloud account")
    if body.name is not None:
        account.name = body.name
    if body.status is not None:
        account.status = body.status
    if body.config is not None:
        account.config = body.config
    if body.credentials is not None:
        account.credentials_encrypted = encrypt_credentials(settings.credential_encryption_key,
                                                            body.credentials)
    db.flush()
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: uuid.UUID, user: CurrentUser = Depends(require_writer),
                   db: Session = DB):
    account = owned.get_account(db, user.id, account_id)
    if account is None:
        raise not_found("Cloud account")
    owned.soft_delete_account(db, account, datetime.now(UTC))


@router.post("/{account_id}/collect-now")
def collect_now(account_id: uuid.UUID, request: Request,
                user: CurrentUser = Depends(rate_limited("collect_limiter")),
                db: Session = DB, settings: Settings = Depends(get_settings)):
    if not user.can_write:
        raise HTTPException(403, "Your role is read-only.")
    account = owned.get_account(db, user.id, account_id)
    if account is None:
        raise not_found("Cloud account")
    adapter = request.app.state.adapter_factory(account.provider_code)
    try:
        inserted = process_account(db, account.id, account.provider_code, adapter, settings,
                                   datetime.now(UTC))
    except NotImplementedError as exc:
        raise HTTPException(400, "This provider integration is not available yet.") from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("collect-now failed: %s", type(exc).__name__)
        raise HTTPException(502, "Collection failed; the provider could not be reached.") from exc
    return {"samples_inserted": inserted}
