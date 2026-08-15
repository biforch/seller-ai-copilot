from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.logging_utils import redact_amazon_detail, redact_sensitive_text
from app.integrations.amazon.lwa import LwaTokenClient
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_REFRESH_TOKEN,
    make_transport,
)


def test_redact_sensitive_text_masks_amazon_patterns():
    raw = (
        f"x-amz-access-token: {TEST_ACCESS_TOKEN} "
        f"x-amz-access-token={TEST_ACCESS_TOKEN} "
        f"refresh_token={TEST_REFRESH_TOKEN} "
        f"access_token={TEST_ACCESS_TOKEN} "
        "client_secret=TEST_CLIENT_SECRET "
        "Atza|IQEBLjAsAexample "
        "Atzr|IQEBLzAtAexample"
    )
    redacted = redact_sensitive_text(raw)
    assert TEST_ACCESS_TOKEN not in redacted
    assert TEST_REFRESH_TOKEN not in redacted
    assert "client_secret=[REDACTED]" in redacted
    assert "x-amz-access-token=[REDACTED]" in redacted
    assert "Atza|[REDACTED]" in redacted
    assert "Atzr|[REDACTED]" in redacted


def test_redact_amazon_detail_masks_json_tokens():
    raw = f'{{"refresh_token":"{TEST_REFRESH_TOKEN}","access_token":"{TEST_ACCESS_TOKEN}"}}'
    redacted = redact_amazon_detail(raw)
    assert TEST_REFRESH_TOKEN not in redacted
    assert TEST_ACCESS_TOKEN not in redacted


def test_redact_amazon_detail_redacts_before_truncating_at_boundary():
    token = "Atza|" + ("X" * 40)
    raw = f"access_token={token}" + ("z" * 200)
    redacted = redact_amazon_detail(raw, max_len=30)
    assert token not in redacted
    assert "access_token=[REDACTED]" in redacted
    assert len(redacted) <= 30


def test_redact_amazon_detail_json_token_crosses_max_len_boundary():
    token = "CROSS_BOUNDARY_SECRET_VALUE"
    prefix = "a" * 480
    raw = f'{prefix}"access_token":"{token}"'
    redacted = redact_amazon_detail(raw, max_len=500)
    assert token not in redacted
    assert len(redacted) <= 500


@pytest.mark.asyncio
async def test_lwa_failure_logs_do_not_include_secrets(amazon_settings, caplog):
    secret = TEST_REFRESH_TOKEN

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f'{{"error":"invalid","refresh_token":"{secret}"}}')

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with caplog.at_level("WARNING"):
        with pytest.raises(Exception):
            await client.exchange_refresh_token(secret)

    combined = redact_amazon_detail(" ".join(record.message for record in caplog.records))
    assert secret not in combined


def test_testing_settings_reject_non_mock_endpoint():
    with pytest.raises(ValueError, match="mock"):
        Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_URL="postgresql://localhost:5432/sellerai_test",
            AMAZON_SP_API_ENDPOINT_MODE="production",
        )
