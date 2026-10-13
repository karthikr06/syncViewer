import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.models import Role, User, Workspace, WorkspaceInvite

ROLE_IDS = {"admin": 1, "developer": 2, "viewer": 3}
MEMBER_ROLES = ("developer", "viewer")  # what an admin can give someone else


class InviteConflict(Exception):
    """The email cannot be invited (already a member here, or has an account elsewhere)."""


def get(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def _with_refs():
    return select(User).options(joinedload(User.role), joinedload(User.workspace))


def get_for_request(session: Session, user_id: uuid.UUID) -> User | None:
    """Load the user with role and workspace and set the audit context, in one round trip."""
    row = session.execute(
        select(User, func.set_config("app.user_id", str(user_id), True))
        .options(joinedload(User.role), joinedload(User.workspace))
        .where(User.id == user_id)
    ).first()
    return row[0] if row else None


def set_audit_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(select(func.set_config("app.user_id", str(user_id), True)))


def provision(session: Session, user_id: uuid.UUID, email: str, now: datetime) -> User | None:
    """First sign-in: join the inviting workspace or start one as admin; None if email is taken."""
    invite = session.scalar(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.email == email, WorkspaceInvite.accepted_at.is_(None))
        .with_for_update()
    )
    created: Workspace | None = None
    if invite is not None:
        workspace_id, role_id = invite.workspace_id, invite.role_id
    else:
        created = Workspace(name=f"{email.split('@')[0]}'s workspace")
        session.add(created)
        session.flush()
        workspace_id, role_id = created.id, ROLE_IDS["admin"]

    inserted = session.execute(
        pg_insert(User)
        .values(id=user_id, email=email, role_id=role_id, workspace_id=workspace_id)
        .on_conflict_do_nothing()  # same id (concurrent first request) or same email
        .returning(User.id)
    ).first()
    if inserted and invite is not None:
        invite.accepted_at = now
    if not inserted and created is not None:
        session.delete(created)  # someone else won the race; drop the unused workspace
    session.flush()
    session.expire_all()
    return session.scalar(_with_refs().where(User.id == user_id))


def touch_login(user: User, now: datetime) -> None:
    user.last_login_at = now


def role_by_name(session: Session, name: str) -> Role | None:
    return session.scalar(select(Role).where(Role.name == name))


# ---- workspace members and invites -------------------------------------------------------------
def members(session: Session, workspace_id: uuid.UUID) -> list[User]:
    return list(session.scalars(
        _with_refs().where(User.workspace_id == workspace_id).order_by(User.created_at)))


def member(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
    return session.scalar(
        _with_refs().where(User.workspace_id == workspace_id, User.id == user_id))


def pending_invites(session: Session, workspace_id: uuid.UUID) -> list[WorkspaceInvite]:
    return list(session.scalars(
        select(WorkspaceInvite).options(joinedload(WorkspaceInvite.role))
        .where(WorkspaceInvite.workspace_id == workspace_id,
               WorkspaceInvite.accepted_at.is_(None))
        .order_by(WorkspaceInvite.created_at.desc())))


def invite(session: Session, workspace_id: uuid.UUID, email: str, role: str,
           invited_by: uuid.UUID) -> WorkspaceInvite:
    """Invite (or re-invite with a new role). Raises InviteConflict when not possible."""
    email = email.strip().lower()
    existing_user = session.scalar(select(User).where(func.lower(User.email) == email))
    if existing_user is not None:
        if existing_user.workspace_id == workspace_id:
            raise InviteConflict("This person is already a member; change their role instead.")
        raise InviteConflict("This email already has a SyncViewer account in another workspace.")
    pending = session.scalar(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.email == email, WorkspaceInvite.accepted_at.is_(None)))
    if pending is not None and pending.workspace_id != workspace_id:
        raise InviteConflict("This email has a pending invite to another workspace.")
    if pending is None:
        pending = WorkspaceInvite(workspace_id=workspace_id, email=email, invited_by=invited_by,
                                  role_id=ROLE_IDS[role])
        session.add(pending)
    else:
        pending.role_id = ROLE_IDS[role]
        pending.invited_by = invited_by
    session.flush()
    session.refresh(pending, ["role"])
    return pending


def get_invite(session: Session, workspace_id: uuid.UUID, invite_id: int) -> WorkspaceInvite | None:
    return session.scalar(
        select(WorkspaceInvite).where(WorkspaceInvite.id == invite_id,
                                      WorkspaceInvite.workspace_id == workspace_id,
                                      WorkspaceInvite.accepted_at.is_(None)))
