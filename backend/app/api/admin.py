import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, not_found, require_admin
from app.models import CollectorRun
from app.repositories import owned
from app.repositories import users as repo
from app.schemas.entities import CollectorRunOut, Page, UserOut
from app.schemas.requests import UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=Page[UserOut])
def list_users(q: str | None = None, page: int = 1, page_size: int = Query(25, ge=1, le=100),
               _: CurrentUser = Depends(require_admin), db: Session = DB):
    rows, total = repo.search(db, q, max(1, page), page_size)
    items = [UserOut(id=u.id, email=u.email, role=u.role.name, is_active=u.is_active,
                     created_at=u.created_at, last_login_at=u.last_login_at) for u in rows]
    return Page(items=items, total=total, page=max(1, page), page_size=page_size)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, admin: CurrentUser = Depends(require_admin),
                db: Session = DB):
    user = repo.get(db, user_id)
    if user is None:
        raise not_found("User")
    demoting = (body.role is not None and body.role != "admin") or body.is_active is False
    if user.id == admin.id and demoting:
        raise HTTPException(400, "You cannot demote or deactivate your own account.")
    if body.role is not None:
        role = repo.role_by_name(db, body.role)
        user.role_id = role.id
    if body.is_active is not None:
        user.is_active = body.is_active
    db.flush()
    db.refresh(user)
    return UserOut(id=user.id, email=user.email, role=user.role.name, is_active=user.is_active,
                   created_at=user.created_at, last_login_at=user.last_login_at)


@router.get("/collector-runs", response_model=Page[CollectorRunOut])
def collector_runs(page: int = 1, page_size: int = Query(25, ge=1, le=100),
                   _: CurrentUser = Depends(require_admin), db: Session = DB):
    items, total, page, page_size = owned.paginate(
        db, select(CollectorRun).order_by(CollectorRun.started_at.desc()), page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
