import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.core.security import AuthError, verify_token
from app.repositories import users as user_repo

bearer = HTTPBearer(auto_error=False)
LOGIN_TOUCH_INTERVAL = timedelta(minutes=5)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# scope="function": the commit above runs BEFORE the response is sent. With the default scope
# FastAPI sends the response first, so a client could read stale data right after a write
# (or get a 2xx for a write whose commit then failed). Use `db: Session = DB` everywhere so
# auth and the route share one session -- the audit context is set on that transaction.
DB = Depends(get_db, scope="function")


@dataclass(frozen=True)
class CurrentUser:
    """`id` is the person (actor); `workspace_id` scopes every piece of monitored data."""

    id: uuid.UUID
    email: str
    role: str
    workspace_id: uuid.UUID
    workspace_name: str = ""
    is_operator: bool = False  # platform operator (ADMIN_EMAILS): may see collector health

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "developer")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = DB,
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = verify_token(creds.credentials, settings)
    except AuthError as exc:
        raise HTTPException(exc.status_code, str(exc),
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError as exc:
        raise HTTPException(401, "invalid token subject") from exc

    now = datetime.now(UTC)
    # also sets app.user_id for this transaction: audit triggers record who made the change
    user = user_repo.get_for_request(db, user_id)
    if user is None:
        email = str(claims.get("email", "")).lower()
        if not email:
            raise HTTPException(401, "token has no email claim")
        user_repo.set_audit_user(db, user_id)
        # joins the workspace that invited this email, or starts a new one as its admin
        user = user_repo.provision(db, user_id, email, now)
        if user is None:
            raise HTTPException(409, "This email is already linked to another account.")
    if not user.is_active:
        raise HTTPException(403, "Your access to this workspace has been removed.")
    if user.last_login_at is None or now - user.last_login_at > LOGIN_TOUCH_INTERVAL:
        user_repo.touch_login(user, now)
    return CurrentUser(user.id, user.email, user.role.name, user.workspace_id,
                       user.workspace.name, user.email.lower() in settings.admin_emails)


def current_user_detached(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Authenticate in a short transaction of its own, for slow endpoints (agent chat) that must
    not keep a pooled connection -- a real server connection behind Supabase's transaction-mode
    pooler -- open while they wait on something else."""
    session = request.app.state.session_factory()
    try:
        user = current_user(creds, session, settings)
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_writer(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.can_write:
        raise HTTPException(403, "Viewers have read-only access.")
    return user


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Workspace admin: manages members and invites."""
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


def require_operator(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Platform operator (ADMIN_EMAILS): sees cross-workspace collector health only."""
    if not user.is_operator:
        raise HTTPException(403, "Operator access required.")
    return user


def rate_limited(limiter_attr: str, auth: Callable = current_user) -> Callable:
    """Dependency factory: limiter lives on app.state so tests can reset it."""

    def dep(request: Request, user: CurrentUser = Depends(auth)) -> CurrentUser:
        limiter: RateLimiter = getattr(request.app.state, limiter_attr)
        limiter.check(str(user.id))
        return user

    return dep


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(404, f"{what} not found")
