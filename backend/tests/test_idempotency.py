import threading
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import GENERATION_IN_PROGRESS, IDEMPOTENCY_CONFLICT
from app.models.generation import Generation
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.product import Product
from app.models.project import Project
from app.prompts.versions import PROMPT_VERSIONS
from app.services.generation_state import (
    InvalidGenerationTransition,
    mark_failed,
    mark_processing,
    mark_succeeded,
)
from app.services.idempotency import canonical_request_hash, require_idempotency_key
from app.services.openai import OpenAIService
from app.services.quota_estimation import estimate_reserve_tokens
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_valid_state_transitions():
    request = GenerationRequest(
        user_id=uuid.uuid4(),
        request_type="listing",
        request_hash="abc",
        status=GenerationRequestStatus.PENDING,
        input={},
    )
    mark_processing(request)
    assert request.status == GenerationRequestStatus.PROCESSING

    mark_succeeded(
        request,
        response_payload={"ok": True},
        generation_id=uuid.uuid4(),
        model="test-model",
        prompt_version=PROMPT_VERSIONS["listing"],
        input_tokens=0,
        output_tokens=0,
        tokens_used=10,
        latency_ms=100,
    )
    assert request.status == GenerationRequestStatus.SUCCEEDED


def test_illegal_transition_is_rejected():
    request = GenerationRequest(
        user_id=uuid.uuid4(),
        request_type="listing",
        request_hash="abc",
        status=GenerationRequestStatus.SUCCEEDED,
        input={},
    )
    with pytest.raises(InvalidGenerationTransition):
        mark_failed(request, error_code="X")


def test_succeeded_cannot_be_overwritten_to_failed():
    request = GenerationRequest(
        user_id=uuid.uuid4(),
        request_type="listing",
        request_hash="abc",
        status=GenerationRequestStatus.SUCCEEDED,
        input={},
        response_payload={"title": "saved"},
    )
    with pytest.raises(InvalidGenerationTransition):
        mark_failed(request, error_code="X")
    assert request.response_payload == {"title": "saved"}


def test_require_idempotency_key_accepts_uuid():
    key = "550e8400-e29b-41d4-a716-446655440000"
    assert require_idempotency_key(key) == key


def test_require_idempotency_key_rejects_invalid_format():
    with pytest.raises(Exception) as exc:
        require_idempotency_key("not-a-uuid")
    assert exc.value.code == 422


@pytest.mark.asyncio
async def test_same_key_same_payload_calls_llm_once(
    client,
    tenant_bundle,
    auth_header,
    valid_listing_payload,
    monkeypatch,
):
    tenant = tenant_bundle("idem-once")
    calls = {"count": 0}

    async def fake_generate_listing(self, **kwargs):
        calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 50
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    key = str(uuid.uuid4())
    headers = {**auth_header(tenant["user"]), "Idempotency-Key": key}
    payload = valid_listing_payload(tenant["project"].id)

    first = client.post("/api/v1/generate/listing", headers=headers, json=payload)
    second = client.post("/api/v1/generate/listing", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert calls["count"] == 1


def test_same_key_different_payload_returns_conflict(
    client,
    tenant_bundle,
    auth_header,
    valid_listing_payload,
    monkeypatch,
):
    tenant = tenant_bundle("idem-conflict")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 10
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    key = str(uuid.uuid4())
    headers = {**auth_header(tenant["user"]), "Idempotency-Key": key}

    first = client.post(
        "/api/v1/generate/listing",
        headers=headers,
        json=valid_listing_payload(tenant["project"].id),
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/generate/listing",
        headers=headers,
        json=valid_listing_payload(tenant["project"].id, name="Different Product"),
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == IDEMPOTENCY_CONFLICT


def test_different_users_can_reuse_same_key(
    client,
    tenant_bundle,
    auth_header,
    valid_listing_payload,
    monkeypatch,
):
    user_a = tenant_bundle("idem-user-a")
    user_b = tenant_bundle("idem-user-b")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 10
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    key = str(uuid.uuid4())
    payload_a = valid_listing_payload(user_a["project"].id)
    payload_b = valid_listing_payload(user_b["project"].id)

    first = client.post(
        "/api/v1/generate/listing",
        headers={**auth_header(user_a["user"]), "Idempotency-Key": key},
        json=payload_a,
    )
    second = client.post(
        "/api/v1/generate/listing",
        headers={**auth_header(user_b["user"]), "Idempotency-Key": key},
        json=payload_b,
    )

    assert first.status_code == 200
    assert second.status_code == 200


def test_processing_duplicate_returns_in_progress(
    client,
    tenant_bundle,
    auth_header,
    db_session,
    valid_listing_payload,
    monkeypatch,
):
    tenant = tenant_bundle("idem-processing")
    key = str(uuid.uuid4())
    payload = valid_listing_payload(tenant["project"].id)
    request_hash = canonical_request_hash(
        {
            "project_id": str(tenant["project"].id),
            "product_id": None,
            "name": payload["name"],
            "category": payload["category"],
            "market": payload["market"],
            "platform": payload["platform"],
            "target_customer": None,
            "advantages": None,
        }
    )

    request = GenerationRequest(
        user_id=tenant["user"].id,
        request_type="listing",
        idempotency_key=key,
        request_hash=request_hash,
        status=GenerationRequestStatus.PROCESSING,
        input={},
        reserved_tokens=estimate_reserve_tokens("listing", {"name": "x"}),
    )
    db_session.add(request)
    db_session.commit()

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 10
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers={**auth_header(tenant["user"]), "Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == GENERATION_IN_PROGRESS


def test_failed_duplicate_does_not_call_llm(
    client,
    tenant_bundle,
    auth_header,
    db_session,
    valid_listing_payload,
    monkeypatch,
):
    tenant = tenant_bundle("idem-failed")
    key = str(uuid.uuid4())
    payload = valid_listing_payload(tenant["project"].id)
    request_hash = canonical_request_hash(
        {
            "project_id": str(tenant["project"].id),
            "product_id": None,
            "name": payload["name"],
            "category": payload["category"],
            "market": payload["market"],
            "platform": payload["platform"],
            "target_customer": None,
            "advantages": None,
        }
    )

    request = GenerationRequest(
        user_id=tenant["user"].id,
        request_type="listing",
        idempotency_key=key,
        request_hash=request_hash,
        status=GenerationRequestStatus.FAILED,
        input={},
        error_code="AI_RESPONSE_INVALID",
    )
    db_session.add(request)
    db_session.commit()

    calls = {"count": 0}

    async def fake_generate_listing(self, **kwargs):
        calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 10
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers={**auth_header(tenant["user"]), "Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "AI_RESPONSE_INVALID"
    assert calls["count"] == 0


def test_concurrent_same_key_only_one_llm_call(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        from app.core.security import get_password_hash
        from app.models.user import User

        user = User(
            email="concurrent-idem@example.com",
            password_hash=get_password_hash("Password1"),
            monthly_tokens=100_000,
        )
        setup.add(user)
        setup.flush()
        project = Project(
            user_id=user.id,
            name="Concurrent Project",
            platform="Amazon",
            market="USA",
        )
        setup.add(project)
        setup.commit()
        setup.refresh(user)
        setup.refresh(project)
        initial_used = user.used_tokens
    finally:
        setup.close()

    key = str(uuid.uuid4())
    body_data = {
        "project_id": project.id,
        "product_id": None,
        "name": "Concurrent Product",
        "category": "Electronics",
        "market": "USA",
        "platform": "Amazon",
        "target_customer": None,
        "advantages": None,
    }
    request_hash = canonical_request_hash(
        {
            "project_id": str(project.id),
            "product_id": None,
            "name": body_data["name"],
            "category": body_data["category"],
            "market": body_data["market"],
            "platform": body_data["platform"],
            "target_customer": None,
            "advantages": None,
        }
    )
    llm_calls = {"count": 0}
    begin_barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []

    async def fake_generate_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 25
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    from app.services.generation_executor import GenerationExecutor

    original_begin = GenerationExecutor.begin_execution

    def begin_at_barrier(self, **kwargs):
        begin_barrier.wait(timeout=5)
        return original_begin(self, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "begin_execution", begin_at_barrier)

    def worker():
        db = session_factory()
        try:
            import asyncio

            from app.core.exceptions import AppException
            from app.services.generation_executor import GenerationExecutor

            executor = GenerationExecutor(db)
            try:
                asyncio.run(
                    executor.execute_listing(
                        user_id=str(user.id),
                        body=type("Body", (), body_data)(),
                        idempotency_key=key,
                        request_hash=request_hash,
                    )
                )
            except AppException as exc:
                if exc.error_code != GENERATION_IN_PROGRESS:
                    raise
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    verify = session_factory()
    try:
        rows = (
            verify.query(GenerationRequest)
            .filter(
                GenerationRequest.user_id == user.id,
                GenerationRequest.idempotency_key == key,
            )
            .all()
        )
        refreshed_user = verify.query(
            __import__("app.models.user", fromlist=["User"]).User
        ).filter_by(id=user.id).one()
        generation_count = (
            verify.query(Generation).filter(Generation.user_id == user.id).count()
        )
        product_count = verify.query(Product).filter(Product.user_id == user.id).count()

        assert len(rows) == 1
        assert rows[0].status == GenerationRequestStatus.SUCCEEDED
        assert llm_calls["count"] == 1
        assert generation_count == 1
        assert product_count <= 1
        assert refreshed_user.reserved_tokens == 0
        assert refreshed_user.used_tokens == initial_used + 25
    finally:
        verify.close()
