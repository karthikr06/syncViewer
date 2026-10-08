from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.agent.runner import run_chat
from app.api.deps import (
    DB,
    CurrentUser,
    current_user,
    current_user_detached,
    get_settings,
    rate_limited,
    require_writer,
)
from app.core.config import Settings
from app.repositories import insights as repo
from app.schemas.entities import DigestOut, Page
from app.schemas.requests import ChatRequest, ChatResponse
from app.services import digests

router = APIRouter(tags=["insights"])


@router.get("/insights/digests", response_model=Page[DigestOut])
def list_digests(page: int = 1, page_size: int = Query(25, ge=1, le=100),
                 user: CurrentUser = Depends(current_user), db: Session = DB):
    items, total, page, page_size = repo.list_digests(db, user.workspace_id, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/insights/digests/generate", response_model=DigestOut, status_code=201)
def generate_digest(days: int = Query(7, ge=1, le=30),
                    user: CurrentUser = Depends(require_writer), db: Session = DB):
    return digests.generate(db, user.workspace_id, datetime.now(UTC), days)


@router.post("/agent/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request,
         user: CurrentUser = Depends(rate_limited("chat_limiter", current_user_detached)),
         settings: Settings = Depends(get_settings)):
    # no DB session held while waiting on the model; tools open short sessions of their own
    return run_chat(request.app.state.session_factory, settings, user.workspace_id, body.message,
                    body.session_id, user.role, user.id)
