from __future__ import annotations

import json

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_SAFE_DETAIL_INVALID,
    AMAZON_SYNC_LEASE_EXPIRED,
    AMAZON_SYNC_LEASE_LOST,
    AmazonError,
)
from app.services.amazon_sync_log_service import (
    SAFE_DETAIL_MAX_BYTES,
    AmazonSyncLogService,
    sanitize_request_id,
    validate_safe_detail,
)
from tests.fixtures.amazon_a32 import create_account_via_service


def test_processing_log_finalize_only_once(db_session, token_encryption_service, user_factory) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
    from app.services.amazon_sync_log_service import AmazonSyncLogService

    log = AmazonSyncLog(
        amazon_account_id=summary.id,
        operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
        status=AmazonSyncStatus.PROCESSING,
    )
    db_session.add(log)
    db_session.commit()

    AmazonSyncLogService.finalize_succeeded(
        db_session,
        account_id=summary.id,
        sync_log_id=log.id,
        items_seen=1,
        items_written=1,
        items_deactivated=0,
    )
    db_session.commit()
    with pytest.raises(AmazonError) as exc_info:
        AmazonSyncLogService.finalize_failed(
            db_session,
            account_id=summary.id,
            sync_log_id=log.id,
            error_code=AMAZON_SYNC_LEASE_EXPIRED,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST


def test_sanitize_request_id_rejects_control_characters() -> None:
    with pytest.raises(AmazonError) as exc_info:
        sanitize_request_id("req\ninjected")
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_finalize_rejects_bool_item_counts(db_session, token_encryption_service, user_factory) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus

    log = AmazonSyncLog(
        amazon_account_id=summary.id,
        operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
        status=AmazonSyncStatus.PROCESSING,
    )
    db_session.add(log)
    db_session.commit()
    with pytest.raises(AmazonError) as exc_info:
        AmazonSyncLogService.finalize_succeeded(
            db_session,
            account_id=summary.id,
            sync_log_id=log.id,
            items_seen=True,  # type: ignore[arg-type]
            items_written=1,
            items_deactivated=0,
        )
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_validate_safe_detail_accepts_small_allowlist_object() -> None:
    detail = validate_safe_detail({"participation_count": 2, "active_count": 2})
    assert detail == {"active_count": 2, "participation_count": 2}


def test_validate_safe_detail_rejects_non_object() -> None:
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail(["not", "object"])  # type: ignore[arg-type]
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_validate_safe_detail_rejects_unknown_key() -> None:
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail({"authorization": "x"})
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


@pytest.mark.parametrize(
    "key",
    ["Access-Token", "refresh_token", "Traceback", "responseBody", "Header-Value"],
)
def test_validate_safe_detail_rejects_forbidden_keys_case_insensitive(key: str) -> None:
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail({key: 1})
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_validate_safe_detail_rejects_nested_values() -> None:
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail({"participation_count": {"nested": 1}})
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_validate_safe_detail_rejects_over_512_bytes_with_multibyte_chars() -> None:
    payload = {"participation_count": "测" * 200}
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    assert len(serialized.encode("utf-8")) > SAFE_DETAIL_MAX_BYTES
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail(payload)
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID


def test_validate_safe_detail_allows_512_byte_boundary() -> None:
    # Build a detail that serializes to exactly 512 bytes.
    filler_len = 512 - len(
        json.dumps({"participation_count": ""}, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    detail = validate_safe_detail({"participation_count": "x" * filler_len})
    encoded = json.dumps(detail, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert len(encoded) <= SAFE_DETAIL_MAX_BYTES


def test_validate_safe_detail_rejects_513_bytes() -> None:
    filler_len = 513 - len(
        json.dumps({"participation_count": ""}, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    with pytest.raises(AmazonError) as exc_info:
        validate_safe_detail({"participation_count": "x" * filler_len})
    assert exc_info.value.error_code == AMAZON_SAFE_DETAIL_INVALID
