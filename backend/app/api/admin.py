"""Workspace membership (admins invite developers and viewers) and platform operator views."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, current_user, not_found, require_admin, require_operator
from app.models import CollectorRun, User, Workspace, WorkspaceInvite
from app.repositories import owned
from app.repositories import users as repo
from app.schemas.entities import (
    CollectorRunOut,
    InviteOut,
    MembersOut,
    Page,
    UserOut,
    WorkspaceOut,
)
from app.schemas.requests import InviteCreate, UserUpdate, WorkspaceUpdate

router = APIRouter(prefix="/workspace", tags=["workspace"])
operator = APIRouter(prefix="/admin", tags=["operator"])


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role.name, is_active=u.is_active,
                   created_at=u.created_at, last_login_at=u.last_login_at)


def _invite_out(i: WorkspaceInvite) -> InviteOut:
    return InviteOut(id=i.id, email=i.email, role=i.role.name, created_at=i.created_at)


@router.get("/members", response_model=MembersOut)
def members(user: CurrentUser = Depends(current_user), db: Session = DB):
    """Everyone can see who is in their workspace; only admins see pending invites."""
    invites = repo.pending_invites(db, user.workspace_id) if user.role == "admin" else []
    return MembersOut(workspace=WorkspaceOut(id=user.workspace_id, name=user.workspace_name),
                      members=[_user_out(u) for u in repo.members(db, user.workspace_id)],
                      invites=[_invite_out(i) for i in invites])


@router.patch("", response_model=WorkspaceOut)
def rename(body: WorkspaceUpdate, admin: CurrentUser = Depends(require_admin), db: Session = DB):
    ws = db.get_one(Workspace, admin.workspace_id)
    ws.name = body.name.strip()
    return WorkspaceOut(id=ws.id, name=ws.name)


@router.post("/invites", response_model=InviteOut, status_code=201)
def invite(body: InviteCreate, admin: CurrentUser = Depends(require_admin), db: Session = DB):
    try:
        inv = repo.invite(db, admin.workspace_id, body.email, body.role, admin.id)
    except repo.InviteConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return _invite_out(inv)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, admin: CurrentUser = Depends(require_admin), db: Session = DB):
    inv = repo.get_invite(db, admin.workspace_id, invite_id)
    if inv is None:
        raise not_found("Invite")
    db.delete(inv)


@router.patch("/members/{user_id}", response_model=UserOut)
def update_member(user_id: uuid.UUID, body: UserUpdate,
                  admin: CurrentUser = Depends(require_admin), db: Session = DB):
    if user_id == admin.id:
        raise HTTPException(400, "You cannot change your own role or access.")
    member = repo.member(db, admin.workspace_id, user_id)
    if member is None:
        raise not_found("Member")
    if member.role.name == "admin":
        raise HTTPException(400, "The workspace admin's role cannot be changed.")
    if body.role is not None:
        member.role_id = repo.ROLE_IDS[body.role]
    if body.is_active is not None:
        member.is_active = body.is_active
    db.flush()
    db.refresh(member, ["role"])
    return _user_out(member)


@operator.get("/collector-runs", response_model=Page[CollectorRunOut])
def collector_runs(page: int = 1, page_size: int = Query(25, ge=1, le=100),
                   _: CurrentUser = Depends(require_operator), db: Session = DB):
    items, total, page, page_size = owned.paginate(
        db, select(CollectorRun).order_by(CollectorRun.started_at.desc()), page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
