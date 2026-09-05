from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.generation import Generation


def _generation(db_session, *, user_id, score: int, created_at: datetime) -> Generation:
    record = Generation(
        user_id=user_id,
        type="listing_audit",
        input={"listing": {"title": "private input"}},
        output={
            "report_id": "00000000-0000-0000-0000-000000000001",
            "created_at": "2000-01-01T00:00:00Z",
            "prompt_version": "listing-audit-prompt-v2",
            "marketplace": "US",
            "language": "en-US",
            "overall_score": score,
            "executive_summary": "A tenant-scoped report.",
            "findings": [],
            "prioritized_actions": [],
            "risk_flags": [],
        },
        tokens_used=10,
        created_at=created_at,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_audit_history_is_tenant_scoped_and_newest_first(
    client, db_session, tenant_bundle, auth_header
) -> None:
    owner = tenant_bundle("audit-history-owner")
    other = tenant_bundle("audit-history-other")
    now = datetime.now(UTC).replace(tzinfo=None)
    older = _generation(db_session, user_id=owner["user"].id, score=41, created_at=now)
    newer = _generation(
        db_session,
        user_id=owner["user"].id,
        score=82,
        created_at=now + timedelta(seconds=1),
    )
    _generation(db_session, user_id=other["user"].id, score=99, created_at=now)

    response = client.get("/api/v1/audits", headers=auth_header(owner["user"]))

    assert response.status_code == 200
    reports = response.json()["data"]
    assert [report["report_id"] for report in reports] == [str(newer.id), str(older.id)]
    assert reports[0]["created_at"].startswith(str((now + timedelta(seconds=1)).date()))
    assert [report["overall_score"] for report in reports] == [82, 41]
    assert all("private input" not in str(report) for report in reports)


def test_audit_detail_returns_owner_report_without_input(
    client, db_session, tenant_bundle, auth_header
) -> None:
    owner = tenant_bundle("audit-detail-owner")
    record = _generation(
        db_session,
        user_id=owner["user"].id,
        score=73,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    response = client.get(
        f"/api/v1/audits/{record.id}", headers=auth_header(owner["user"])
    )

    assert response.status_code == 200
    assert response.json()["data"]["report_id"] == str(record.id)
    assert response.json()["data"]["created_at"].startswith(str(record.created_at.date()))
    assert "private input" not in response.text


def test_audit_detail_uses_tenant_safe_not_found(
    client, db_session, tenant_bundle, auth_header
) -> None:
    owner = tenant_bundle("audit-hidden-owner")
    other = tenant_bundle("audit-hidden-other")
    record = _generation(
        db_session,
        user_id=owner["user"].id,
        score=73,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    response = client.get(
        f"/api/v1/audits/{record.id}", headers=auth_header(other["user"])
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "AUDIT_REPORT_NOT_FOUND"
    assert str(owner["user"].id) not in response.text


def test_audit_history_requires_cookie_session(client) -> None:
    response = client.get("/api/v1/audits")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_SESSION_INVALID"
