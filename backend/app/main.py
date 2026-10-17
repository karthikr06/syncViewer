import logging
import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import accounts, admin, alerting, insights, internal, recommendations, resources, sync
from app.api.deps import CurrentUser, current_user
from app.collector.adapters import ProviderAdapter, get_adapter
from app.core.config import Settings, load_settings_or_exit
from app.core.db import get_session_factory
from app.core.ratelimit import RateLimiter
from app.schemas.entities import MeOut, WorkspaceOut

log = logging.getLogger("api")
API_REQUIRED = ["DATABASE_URL", "CREDENTIAL_ENCRYPTION_KEY"]


def create_app(
    settings: Settings | None = None,
    session_factory=None,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
) -> FastAPI:
    settings = settings or load_settings_or_exit(API_REQUIRED)
    if not (settings.supabase_jwks_url or settings.supabase_jwt_secret):
        raise SystemExit("Configuration error: set SUPABASE_JWKS_URL (or SUPABASE_JWT_SECRET)")

    app = FastAPI(
        title="SyncViewer API",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory or get_session_factory(settings.database_url)
    app.state.adapter_factory = adapter_factory or (lambda code: get_adapter(code, settings))
    app.state.collect_limiter = RateLimiter(limit=6, window_seconds=60)
    app.state.chat_limiter = RateLimiter(limit=12, window_seconds=60)
    app.state.action_limiter = RateLimiter(limit=20, window_seconds=60)

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization",
                                                                         "Content-Type"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error [request %s]", rid)
            response = JSONResponse(
                {"detail": "Something went wrong on our side.", "request_id": rid},
                status_code=500)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # noqa: ARG001
        rid = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        log.exception("unhandled error [request %s]", rid)
        return JSONResponse({"detail": "Something went wrong on our side.", "request_id": rid},
                            status_code=500)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    v1 = APIRouter(prefix="/api/v1")

    @v1.get("/me", response_model=MeOut, tags=["me"])
    def me(user: CurrentUser = Depends(current_user)):
        return MeOut(id=user.id, email=user.email, role=user.role, is_operator=user.is_operator,
                     workspace=WorkspaceOut(id=user.workspace_id, name=user.workspace_name))

    for r in (accounts.router, resources.router, alerting.rules, alerting.alerts,
              recommendations.router, insights.router, sync.router, admin.router,
              admin.operator, internal.router):
        v1.include_router(r)
    app.include_router(v1)
    return app
