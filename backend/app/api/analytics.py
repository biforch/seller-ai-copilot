import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsSummary, AnalyticsSummaryApiResponse
from app.services.product_analytics_service import build_analytics_summary

router = APIRouter()


def require_admin(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.id == uuid.UUID(str(current_user["id"]))).one_or_none()
    if user is None or not user.is_admin:
        raise AppException("Administrator access required", status.HTTP_403_FORBIDDEN)
    return user


@router.get("/summary", response_model=AnalyticsSummaryApiResponse)
def analytics_summary(
    days: int = Query(30, ge=7, le=90),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    payload = AnalyticsSummary.model_validate(build_analytics_summary(db, days=days))
    return success_response(data=payload.model_dump(mode="json"))
