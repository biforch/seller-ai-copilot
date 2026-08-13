import threading
import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import QUOTA_EXCEEDED, AppException
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.project import Project
from app.services.idempotency import canonical_request_hash
from app.services.openai import OpenAIService
from app.services.quota import (
    lock_user_for_quota,
    release_reserved_tokens,
    reserve_tokens,
    settle_reserved_to_consumed,
)
from app.services.quota_estimation import estimate_reserve_tokens
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_reserve_succeeds_when_quota_available(db_session, user_factory):
    user = user_factory("quota-reserve@example.com")
    user.monthly_tokens = 1000
    user.used_tokens = 0
    user.reserved_tokens = 0
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    reserve_tokens(locked, 500)
    db_session.add(locked)
    db_session.commit()
    db_session.refresh(locked)

    assert locked.reserved_tokens == 500
    assert locked.used_tokens == 0


def test_reserve_fails_when_quota_insufficient(db_session, user_factory):
    user = user_factory("quota-block@example.com")
    user.monthly_tokens = 1000
    user.used_tokens = 900
    user.reserved_tokens = 50
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    with pytest.raises(AppException) as exc:
        reserve_tokens(locked, estimate_reserve_tokens("listing", {"name": "x"}))
    assert exc.value.error_code == QUOTA_EXCEEDED


def test_release_reserved_before_llm(db_session, user_factory):
    user = user_factory("quota-release@example.com")
    user.monthly_tokens = 1000
    user.reserved_tokens = 200
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    release_reserved_tokens(locked, 200)
    db_session.add(locked)
    db_session.commit()
    db_session.refresh(locked)

    assert locked.reserved_tokens == 0
    assert locked.used_tokens == 0


def test_settle_moves_reserved_to_consumed(db_session, user_factory):
    user = user_factory("quota-settle@example.com")
    user.monthly_tokens = 1000
    user.reserved_tokens = 500
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    settle_reserved_to_consumed(locked, reserved_amount=500, consumed_amount=120)
    db_session.add(locked)
    db_session.commit()
    db_session.refresh(locked)

    assert locked.reserved_tokens == 0
    assert locked.used_tokens == 120


def test_overage_blocks_subsequent_reserve_with_quota_exceeded(db_session, user_factory):
    user = user_factory("quota-overage@example.com")
    user.monthly_tokens = 100
    user.used_tokens = 90
    user.reserved_tokens = 0
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    settle_reserved_to_consumed(locked, reserved_amount=50, consumed_amount=60)
    db_session.add(locked)
    db_session.commit()
    db_session.refresh(locked)

    assert locked.used_tokens == 150
    assert locked.reserved_tokens == 0

    again = lock_user_for_quota(db_session, user.id)
    with pytest.raises(AppException) as exc:
        reserve_tokens(
            again,
            estimate_reserve_tokens(
                "listing",
                {"name": "x", "category": "c", "market": "USA", "platform": "Amazon"},
            ),
        )
    assert exc.value.error_code == QUOTA_EXCEEDED


def test_usage_api_remaining_tokens_never_negative(client, user_factory, auth_header, db_session):
    user = user_factory("usage-clamp@example.com")
    user.monthly_tokens = 100
    user.used_tokens = 120
    user.reserved_tokens = 10
    db_session.add(user)
    db_session.commit()

    response = client.get("/api/v1/user/usage", headers=auth_header(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["remaining_tokens"] == 0
    assert data["reserved_tokens"] == 10


def test_idempotent_replay_does_not_double_consume(
    client,
    tenant_bundle,
    auth_and_idempotency,
    isolated_client_ip,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    tenant = tenant_bundle("quota-idem")
    tenant["user"].monthly_tokens = 10_000
    tenant["user"].used_tokens = 0
    tenant["user"].reserved_tokens = 0
    db_session.add(tenant["user"])
    db_session.commit()

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 80
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    key = str(uuid.uuid4())
    headers = {
        **auth_and_idempotency(tenant["user"]),
        **isolated_client_ip("10.30.40.51"),
        "Idempotency-Key": key,
    }
    payload = valid_listing_payload(tenant["project"].id)

    first = client.post("/api/v1/generate/listing", headers=headers, json=payload)
    second = client.post("/api/v1/generate/listing", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200

    db_session.refresh(tenant["user"])
    assert tenant["user"].used_tokens == 80
    assert tenant["user"].reserved_tokens == 0


def test_insufficient_quota_does_not_call_llm(
    client,
    tenant_bundle,
    auth_and_idempotency,
    isolated_client_ip,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    tenant = tenant_bundle("quota-no-llm")
    tenant["user"].monthly_tokens = 100
    tenant["user"].used_tokens = 100
    tenant["user"].reserved_tokens = 0
    db_session.add(tenant["user"])
    db_session.commit()

    calls = {"count": 0}

    async def fake_generate_listing(self, **kwargs):
        calls["count"] += 1
        return VALID_LISTING_OUTPUT

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers={**auth_and_idempotency(tenant["user"]), **isolated_client_ip("10.30.40.52")},
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["error_code"] == QUOTA_EXCEEDED
    assert calls["count"] == 0


def test_concurrent_last_quota_slot(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        from app.core.security import get_password_hash
        from app.models.user import User

        canonical_input = {
            "project_id": None,
            "product_id": None,
            "name": "Product race",
            "category": "Electronics",
            "market": "USA",
            "platform": "Amazon",
            "target_customer": None,
            "advantages": None,
        }
        reserve_amount = estimate_reserve_tokens("listing", canonical_input)
        user = User(
            email="quota-race@example.com",
            password_hash=get_password_hash("Password1"),
            monthly_tokens=reserve_amount + 100,
            used_tokens=100,
        )
        setup.add(user)
        setup.flush()
        project = Project(
            user_id=user.id,
            name="Race Project",
            platform="Amazon",
            market="USA",
        )
        setup.add(project)
        setup.commit()
        setup.refresh(user)
        setup.refresh(project)
        canonical_input["project_id"] = str(project.id)
        request_hash = canonical_request_hash(canonical_input)
    finally:
        setup.close()

    results: list[str] = []
    begin_barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []

    from app.services.generation_executor import GenerationExecutor

    original_begin = GenerationExecutor.begin_execution

    def begin_at_barrier(self, **kwargs):
        begin_barrier.wait(timeout=5)
        return original_begin(self, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "begin_execution", begin_at_barrier)

    def worker(label: str):
        db = session_factory()
        try:
            from app.services.generation_executor import GenerationExecutor

            executor = GenerationExecutor(db)
            try:
                executor.begin_execution(
                    user_id=user.id,
                    request_type="listing",
                    idempotency_key=str(uuid.uuid4()),
                    request_hash=request_hash,
                    input_data=canonical_input,
                    project_id=project.id,
                )
                results.append("ok")
            except AppException as exc:
                if exc.error_code == QUOTA_EXCEEDED:
                    results.append(QUOTA_EXCEEDED)
                else:
                    results.append(f"error:{exc.error_code}")
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    assert results.count("ok") == 1
    assert results.count(QUOTA_EXCEEDED) == 1

    verify = session_factory()
    try:
        from app.models.user import User

        refreshed = verify.query(User).filter(User.id == user.id).one()
        assert refreshed.reserved_tokens == reserve_amount
        processing = (
            verify.query(GenerationRequest)
            .filter(
                GenerationRequest.user_id == user.id,
                GenerationRequest.status == GenerationRequestStatus.PROCESSING,
            )
            .all()
        )
        assert len(processing) == 1
        assert (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.user_id == user.id)
            .count()
            == 1
        )
    finally:
        verify.close()
