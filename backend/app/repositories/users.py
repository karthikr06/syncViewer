import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.models import Role, User

ROLE_IDS = {"admin": 1, "user": 2, "viewer": 3}


def get(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def get_for_request(session: Session, user_id: uuid.UUID) -> User | None:
    """The user with their role AND the audit context for this transaction, in one round trip
    (each round trip to a remote database costs 100+ ms). Returns None for a first login, in
    which case the caller provisions the user and sets the audit context itself."""
    row = session.execute(
        select(User, func.set_config("app.user_id", str(user_id), True))
        .options(joinedload(User.role))
        .where(User.id == user_id)
    ).first()
    return row[0] if row else None


def set_audit_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(select(func.set_config("app.user_id", str(user_id), True)))


def provision(session: Session, user_id: uuid.UUID, email: str, role_id: int) -> User:
    """Create the users row on first login; safe under concurrent first requests."""
    session.execute(pg_insert(User).values(id=user_id, email=email, role_id=role_id)
                    .on_conflict_do_nothing(index_elements=[User.id]))
    session.flush()
    session.expire_all()
    return session.get_one(User, user_id)


def touch_login(user: User, now: datetime) -> None:
    user.last_login_at = now


def search(session: Session, q: str | None, page: int, page_size: int
           ) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.icontains(q, autoescape=True))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(User.created_at.desc())
                           .offset((page - 1) * page_size).limit(page_size)).all()
    return list(rows), total


def role_by_name(session: Session, name: str) -> Role | None:
    return session.scalar(select(Role).where(Role.name == name))


def count_active_admins(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).join(Role, Role.id == User.role_id)
        .where(Role.name == "admin", User.is_active.is_(True))) or 0
