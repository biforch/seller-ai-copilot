"""Amazon sync log finalization and safe_detail validation."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_SYNC_LEASE_LOST,
    amazon_safe_detail_invalid_error,
    amazon_sync_lease_lost_error,
)
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncStatus

SAFE_DETAIL_MAX_BYTES = 512
MAX_SYNC_ITEM_COUNT = 1_000_000

ALLOWED_SAFE_DETAIL_KEYS = frozenset(
    {
        "participation_count",
        "active_count",
        "deactivated_count",
        "reactivated_count",
        "pages_seen",
    }
)

_FORBIDDEN_KEY_PATTERN = re.compile(
    r"(authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"api[_-]?key|password|ciphertext|pepper|traceback|header|body|secret|token)",
    re.IGNORECASE,
)

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def _validate_item_count(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise amazon_safe_detail_invalid_error()
    if value < 0 or value > MAX_SYNC_ITEM_COUNT:
        raise amazon_safe_detail_invalid_error()
    return value


def sanitize_request_id(request_id: str | None) -> str | None:
    if request_id is None:
        return None
    cleaned = request_id.strip()
    if not cleaned:
        return None
    if _CONTROL_CHAR_PATTERN.search(cleaned):
        raise amazon_safe_detail_invalid_error()
    return cleaned[:64]


def validate_safe_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    if not isinstance(detail, dict):
        raise amazon_safe_detail_invalid_error()
    if not detail:
        return {}

    normalized: dict[str, Any] = {}
    for key, value in detail.items():
        if not isinstance(key, str) or not key:
            raise amazon_safe_detail_invalid_error()
        if key not in ALLOWED_SAFE_DETAIL_KEYS:
            raise amazon_safe_detail_invalid_error()
        if _FORBIDDEN_KEY_PATTERN.search(key):
            raise amazon_safe_detail_invalid_error()
        if key == "pages_seen":
            normalized[key] = _validate_item_count(value, field_name=key)
        elif type(value) is bool:
            normalized[key] = value
        elif type(value) is int:
            if value < 0 or value > MAX_SYNC_ITEM_COUNT:
                raise amazon_safe_detail_invalid_error()
            normalized[key] = value
        elif type(value) is str:
            if _FORBIDDEN_KEY_PATTERN.search(value):
                raise amazon_safe_detail_invalid_error()
            normalized[key] = value
        else:
            raise amazon_safe_detail_invalid_error()

    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    if len(payload.encode("utf-8")) > SAFE_DETAIL_MAX_BYTES:
        raise amazon_safe_detail_invalid_error()
    return normalized


class AmazonSyncLogService:
    @staticmethod
    def _load_processing_log(
        db: Session,
        *,
        account_id: uuid.UUID,
        sync_log_id: uuid.UUID,
    ) -> AmazonSyncLog:
        sync_log = (
            db.query(AmazonSyncLog)
            .filter(
                AmazonSyncLog.id == sync_log_id,
                AmazonSyncLog.amazon_account_id == account_id,
                AmazonSyncLog.status == AmazonSyncStatus.PROCESSING,
            )
            .with_for_update()
            .one_or_none()
        )
        if sync_log is None:
            raise amazon_sync_lease_lost_error()
        return sync_log

    @staticmethod
    def finalize_succeeded(
        db: Session,
        *,
        account_id: uuid.UUID,
        sync_log_id: uuid.UUID,
        items_seen: int,
        items_written: int,
        items_deactivated: int,
        request_id: str | None = None,
        safe_detail: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> AmazonSyncLog:
        _validate_item_count(items_seen, field_name="items_seen")
        _validate_item_count(items_written, field_name="items_written")
        _validate_item_count(items_deactivated, field_name="items_deactivated")

        sync_log = AmazonSyncLogService._load_processing_log(
            db,
            account_id=account_id,
            sync_log_id=sync_log_id,
        )
        sync_log.status = AmazonSyncStatus.SUCCEEDED
        sync_log.items_seen = items_seen
        sync_log.items_written = items_written
        sync_log.items_deactivated = items_deactivated
        sync_log.request_id = sanitize_request_id(request_id)
        sync_log.error_code = None
        sync_log.safe_detail = validate_safe_detail(safe_detail)
        sync_log.finished_at = finished_at
        db.add(sync_log)
        return sync_log

    @staticmethod
    def finalize_failed(
        db: Session,
        *,
        account_id: uuid.UUID,
        sync_log_id: uuid.UUID,
        error_code: str,
        request_id: str | None = None,
        safe_detail: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> AmazonSyncLog:
        if not error_code or error_code == AMAZON_SYNC_LEASE_LOST:
            raise amazon_safe_detail_invalid_error()

        sync_log = AmazonSyncLogService._load_processing_log(
            db,
            account_id=account_id,
            sync_log_id=sync_log_id,
        )
        sync_log.status = AmazonSyncStatus.FAILED
        sync_log.error_code = error_code[:64]
        sync_log.request_id = sanitize_request_id(request_id)
        sync_log.safe_detail = validate_safe_detail(safe_detail)
        sync_log.finished_at = finished_at
        db.add(sync_log)
        return sync_log
