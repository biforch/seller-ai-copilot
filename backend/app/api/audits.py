from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.models.generation import Generation

router = APIRouter()


def _report_payload(record: Generation) -> dict:
    payload = dict(record.output)
    payload.setdefault("report_id", str(record.id))
    payload.setdefault("created_at", record.created_at.isoformat() if record.created_at else None)
    return payload


@router.get("")
def list_audits(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(Generation)
        .filter(
            Generation.user_id == uuid.UUID(str(current_user["id"])),
            Generation.type == "listing_audit",
        )
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(20)
        .all()
    )
    return success_response(data=[_report_payload(record) for record in records])


@router.get("/{report_id}")
def get_audit(
    report_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = (
        db.query(Generation)
        .filter(
            Generation.id == report_id,
            Generation.user_id == uuid.UUID(str(current_user["id"])),
            Generation.type == "listing_audit",
        )
        .one_or_none()
    )
    if record is None:
        raise AppException(
            "Audit report not found",
            code=status.HTTP_404_NOT_FOUND,
            error_code="AUDIT_REPORT_NOT_FOUND",
        )
    return success_response(data=_report_payload(record))
