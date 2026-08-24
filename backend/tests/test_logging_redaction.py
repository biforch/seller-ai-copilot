from app.core.logging_utils import redact_email, redact_sensitive_text


def test_redact_email_masks_local_part():
    assert redact_email("seller@example.com") == "s***@example.com"


def test_redact_sensitive_text_masks_bearer_api_key_jwt_and_url_credentials():
    raw = (
        "Authorization: Bearer abc.def.ghi api_key=secret "
        "refresh_token=rtok access_token=atok client_secret=csec "
        "eyJhbGci.test.signature postgresql://user:pass@localhost/db"
    )
    redacted = redact_sensitive_text(raw)
    assert "Bearer [REDACTED]" in redacted
    assert "api_key=secret" not in redacted
    assert "rtok" not in redacted
    assert "atok" not in redacted
    assert "client_secret=csec" not in redacted
    assert "jwt:[REDACTED]" in redacted
    assert "user:pass" not in redacted


def test_redact_sensitive_text_masks_oauth_query_values():
    raw = (
        "GET /api/v1/amazon/oauth/callback?state=state-canary"
        "&spapi_oauth_code=code-canary&selling_partner_id=seller-canary HTTP/1.1"
    )
    redacted = redact_sensitive_text(raw)
    assert "state-canary" not in redacted
    assert "code-canary" not in redacted
    assert "seller-canary" not in redacted
    assert "state=[REDACTED]" in redacted
    assert "spapi_oauth_code=[REDACTED]" in redacted
