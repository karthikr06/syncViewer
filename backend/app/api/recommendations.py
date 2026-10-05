from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user, get_db, not_found, require_writer
from app.repositories import owned
from app.schemas.entities import Page, RecommendationOut
from app.schemas.requests import RecommendationUpdate

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=Page[RecommendationOut])
def list_recommendations(status: str | None = None, category: str | None = None,
                         severity: str | None = None, q: str | None = None, page: int = 1,
                         page_size: int = Query(25, ge=1, le=100),
                         user: CurrentUser = Depends(current_user),
                         db: Session = Depends(get_db)):
    items, total, page, page_size = owned.list_recommendations(
        db, user.id, status, category, severity, q, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.patch("/{rec_id}", response_model=RecommendationOut)
def update_status(rec_id: int, body: RecommendationUpdate,
                  user: CurrentUser = Depends(require_writer), db: Session = Depends(get_db)):
    rec = owned.get_recommendation(db, user.id, rec_id)
    if rec is None:
        raise not_found("Recommendation")
    rec.status = body.status
    db.flush()
    return rec
