import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
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


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: str

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "user")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
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
    user = user_repo.get(db, user_id)
    if user is None:
        email = str(claims.get("email", "")).lower()
        if not email:
            raise HTTPException(401, "token has no email claim")
        role = "admin" if email in settings.admin_emails else "user"
        user = user_repo.provision(db, user_id, email, user_repo.ROLE_IDS[role])
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated.")
    if user.last_login_at is None or now - user.last_login_at > LOGIN_TOUCH_INTERVAL:
        user_repo.touch_login(user, now)
    # audit triggers record who made the change
    db.execute(select(func.set_config("app.user_id", str(user.id), True)))
    return CurrentUser(user.id, user.email, user.role.name)


def require_writer(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.can_write:
        raise HTTPException(403, "Your role is read-only.")
    return user


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


def rate_limited(limiter_attr: str) -> Callable:
    """Dependency factory: limiter lives on app.state so tests can reset it."""

    def dep(request: Request, user: CurrentUser = Depends(current_user)) -> CurrentUser:
        limiter: RateLimiter = getattr(request.app.state, limiter_attr)
        limiter.check(str(user.id))
        return user

    return dep


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(404, f"{what} not found")
