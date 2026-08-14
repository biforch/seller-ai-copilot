"""Fault-injection tests for generation executor — deterministic failure modes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import (
    AI_RESPONSE_INVALID,
    GENERATION_FINALIZE_FAILED,
    GENERATION_IN_PROGRESS,
    AppException,
)
from app.models.generation import Generation
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.listing_proposal import ListingProposal
from app.models.product import Product
from app.models.project import Project
from app.models.user import User
from app.services.generation_executor import (
    ExecutionContext,
    GenerationExecutor,
    find_stale_processing_requests,
)
from app.services.idempotency import canonical_request_hash
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def _listing_fixture(session_factory):
    from app.core.security import get_password_hash

    db = session_factory()
    try:
        user = User(
            email=f"fault-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=get_password_hash("Password1"),
            monthly_tokens=500_000,
            used_tokens=0,
            reserved_tokens=0,
        )
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            name="Fault Project",
            platform="Amazon",
            market="USA",
        )
        db.add(project)
        db.commit()
        db.refresh(user)
        db.refresh(project)
    finally:
        db.close()

    body = type(
        "Body",
        (),
        {
            "project_id": project.id,
            "product_id": None,
            "name": "Fault Product",
            "category": "Electronics",
            "market": "USA",
            "platform": "Amazon",
            "target_customer": None,
            "advantages": None,
        },
    )()
    canonical_input = {
        "project_id": str(project.id),
        "product_id": None,
        "name": body.name,
        "category": body.category,
        "market": body.market,
        "platform": body.platform,
        "target_customer": None,
        "advantages": None,
    }
    key = str(uuid.uuid4())
    request_hash = canonical_request_hash(canonical_input)
    return user, project, body, key, request_hash, canonical_input


def _assert_failed_cleanup(
    verify,
    *,
    user_id,
    idempotency_key,
    llm_calls: int,
    product_count: int = 0,
    generation_count: int = 0,
    error_code: str = GENERATION_FINALIZE_FAILED,
):
    user = verify.query(User).filter(User.id == user_id).one()
    record = (
        verify.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == idempotency_key)
        .one()
    )
    assert record.status == GenerationRequestStatus.FAILED
    assert record.error_code == error_code
    assert user.reserved_tokens == 0
    assert verify.query(Product).filter(Product.user_id == user_id).count() == product_count
    assert verify.query(Generation).filter(Generation.user_id == user_id).count() == generation_count
    assert llm_calls == 1


def test_begin_execution_flush_before_commit_no_request_no_reserve(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, _body, key, request_hash, canonical_input = _listing_fixture(session_factory)
    canonical_input["project_id"] = str(project.id)

    db = session_factory()
    executor = GenerationExecutor(db)
    flush_calls = {"count": 0}

    def failing_flush(*args, **kwargs):
        flush_calls["count"] += 1
        raise SQLAlchemyError("simulated flush failure")

    monkeypatch.setattr(db, "flush", failing_flush)

    with pytest.raises(SQLAlchemyError):
        executor.begin_execution(
            user_id=user.id,
            request_type="listing",
            idempotency_key=key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id,
        )
    db.rollback()
    db.close()

    verify = session_factory()
    try:
        assert (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .count()
            == 0
        )
        refreshed = verify.query(User).filter(User.id == user.id).one()
        assert refreshed.reserved_tokens == 0
    finally:
        verify.close()


def test_begin_execution_commit_failure_rollback_no_llm(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, canonical_input = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        return VALID_LISTING_OUTPUT

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    db = session_factory()
    executor = GenerationExecutor(db)
    original_commit = db.commit
    commit_calls = {"count": 0}

    def failing_commit():
        commit_calls["count"] += 1
        if commit_calls["count"] == 1:
            raise SQLAlchemyError("simulated commit failure")
        return original_commit()

    monkeypatch.setattr(db, "commit", failing_commit)

    with pytest.raises(SQLAlchemyError):
        executor.begin_execution(
            user_id=user.id,
            request_type="listing",
            idempotency_key=key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id,
        )
    db.close()

    verify = session_factory()
    try:
        assert (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .count()
            == 0
        )
        refreshed = verify.query(User).filter(User.id == user.id).one()
        assert refreshed.reserved_tokens == 0
        assert llm_calls["count"] == 0
    finally:
        verify.close()


def test_tx1_success_stays_processing_before_llm_for_stale_detection(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, _body, key, request_hash, canonical_input = _listing_fixture(session_factory)

    db = session_factory()
    try:
        begin = GenerationExecutor(db).begin_execution(
            user_id=user.id,
            request_type="listing",
            idempotency_key=key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id,
        )
        record = begin.request
        record.started_at = datetime.utcnow() - timedelta(minutes=90)
        db.add(record)
        db.commit()
    finally:
        db.close()

    verify = session_factory()
    try:
        row = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        assert row.status == GenerationRequestStatus.PROCESSING
        stale = find_stale_processing_requests(verify, older_than_minutes=30)
        assert any(item.id == row.id for item in stale)
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_compute_listing_score_failure_marks_failed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 55
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.compute_listing_score",
        lambda _result: (_ for _ in ()).throw(RuntimeError("score failed")),
    )

    db = session_factory()
    try:
        with pytest.raises(Exception) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_prepare_response_payload_failure_marks_failed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 40
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.prepare_response_payload",
        lambda _payload: (_ for _ in ()).throw(ValueError("payload too large")),
    )

    db = session_factory()
    try:
        with pytest.raises(Exception) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_product_resolve_failure_marks_failed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 35
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.ProductService.resolve_or_create",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("product flush failed")),
    )

    db = session_factory()
    try:
        with pytest.raises(Exception) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_generation_flush_failure_marks_failed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 30
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    db = session_factory()
    original_flush = db.flush
    flush_count = {"n": 0}

    def selective_flush(*args, **kwargs):
        flush_count["n"] += 1
        if flush_count["n"] >= 3:
            raise SQLAlchemyError("generation insert failed")
        return original_flush(*args, **kwargs)

    flush_count = {"n": 0}
    monkeypatch.setattr(db, "flush", selective_flush)

    try:
        with pytest.raises(Exception) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_quota_settle_failure_marks_failed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 25
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.settle_reserved_to_consumed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("settle failed")),
    )

    db = session_factory()
    try:
        with pytest.raises(Exception) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_tx2_commit_failure_confirms_db_state_no_duplicate_llm(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    original_finalize = GenerationExecutor._finalize_success

    def finalize_with_commit_failure(self, *args, **kwargs):
        self.db.commit = lambda: (_ for _ in ()).throw(SQLAlchemyError("tx2 commit failed"))
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "_finalize_success", finalize_with_commit_failure)

    db = session_factory()
    try:
        with pytest.raises(AppException) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db.close()

    verify = session_factory()
    try:
        assert llm_calls["count"] == 1
        record = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        assert record.status == GenerationRequestStatus.FAILED
        assert verify.query(Generation).filter(Generation.user_id == user.id).count() == 0
        assert verify.query(Product).filter(Product.user_id == user.id).count() == 0
        refreshed = verify.query(User).filter(User.id == user.id).one()
        assert refreshed.reserved_tokens == 0
    finally:
        verify.close()

    db2 = session_factory()
    try:
        with pytest.raises(AppException) as replay_exc:
            await GenerationExecutor(db2).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert llm_calls["count"] == 1
        assert replay_exc.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db2.close()


def test_finalize_failure_cleanup_failure_leaves_stale_processing(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, _body, key, request_hash, canonical_input = _listing_fixture(session_factory)

    db = session_factory()
    try:
        begin = GenerationExecutor(db).begin_execution(
            user_id=user.id,
            request_type="listing",
            idempotency_key=key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id,
        )
        ctx = ExecutionContext(
            request_id=begin.request.id,
            user_id=user.id,
            project=project,
            reserve_amount=begin.request.reserved_tokens,
            request_type="listing",
        )
        begin.request.started_at = datetime.utcnow() - timedelta(minutes=90)
        db.add(begin.request)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        GenerationExecutor,
        "_attempt_finalize_failure_fresh",
        lambda *_args, **_kwargs: False,
    )

    db2 = session_factory()
    try:
        executor = GenerationExecutor(db2)
        with pytest.raises(Exception) as exc_info:
            executor._handle_post_llm_error(
                ctx,
                RuntimeError("simulated finalize error"),
                latency_ms=100,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED  # type: ignore[attr-defined]
    finally:
        db2.close()

    verify = session_factory()
    try:
        row = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        assert row.status == GenerationRequestStatus.PROCESSING
        stale = find_stale_processing_requests(verify, older_than_minutes=30)
        assert any(item.id == row.id for item in stale)
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_finalize_app_exception_marks_failed_and_releases_quota(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 45
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.prepare_response_payload",
        lambda _payload: (_ for _ in ()).throw(
            AppException(
                message="Payload rejected during finalize",
                code=status.HTTP_409_CONFLICT,
                error_code=GENERATION_IN_PROGRESS,
            )
        ),
    )

    db = session_factory()
    try:
        with pytest.raises(AppException) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
    finally:
        verify.close()

    replay = session_factory()
    try:
        with pytest.raises(AppException) as replay_exc:
            await GenerationExecutor(replay).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert replay_exc.value.error_code == GENERATION_FINALIZE_FAILED
        assert llm_calls["count"] == 1
    finally:
        replay.close()


def test_finalize_app_exception_after_concurrent_success_returns_saved_payload(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, _body, key, request_hash, canonical_input = _listing_fixture(session_factory)

    db = session_factory()
    try:
        begin = GenerationExecutor(db).begin_execution(
            user_id=user.id,
            request_type="listing",
            idempotency_key=key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id,
        )
        ctx = ExecutionContext(
            request_id=begin.request.id,
            user_id=user.id,
            project=project,
            reserve_amount=begin.request.reserved_tokens,
            request_type="listing",
        )
        saved_payload = {
            "project_id": str(project.id),
            "title": "Already Saved",
            "bullets": ["a"],
            "description": "d",
            "keywords": ["k"],
            "score": 90,
            "tokens_used": 12,
        }
        from app.services.generation_state import mark_succeeded

        mark_succeeded(
            begin.request,
            response_payload=saved_payload,
            generation_id=None,
            model="test-model",
            prompt_version="listing-v1",
            input_tokens=0,
            output_tokens=0,
            tokens_used=12,
            latency_ms=50,
        )
        db.add(begin.request)
        db.commit()
    finally:
        db.close()

    worker = session_factory()
    try:
        def finalize_raises() -> dict:
            raise AppException(
                message="Concurrent worker lost finalize race",
                code=status.HTTP_409_CONFLICT,
                error_code=GENERATION_IN_PROGRESS,
            )

        result = GenerationExecutor(worker)._finalize_with_boundary(
            ctx,
            latency_ms=100,
            finalize_fn=finalize_raises,
        )
        assert result == saved_payload
    finally:
        worker.close()


def test_llm_invalid_response_marks_failed_and_releases_quota(
    client,
    tenant_bundle,
    auth_and_idempotency,
    isolated_client_ip,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    tenant = tenant_bundle("fault-ai-invalid")
    key = str(uuid.uuid4())

    async def broken_listing(self, **kwargs):
        from app.core.exceptions import ai_response_invalid_exception

        raise ai_response_invalid_exception()

    monkeypatch.setattr(OpenAIService, "generate_listing", broken_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_and_idempotency(tenant["user"], key),
            **isolated_client_ip("10.40.50.1"),
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 502
    assert response.json()["error_code"] == AI_RESPONSE_INVALID

    db_session.refresh(tenant["user"])
    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == key)
        .one()
    )
    assert record.status == GenerationRequestStatus.FAILED
    assert tenant["user"].reserved_tokens == 0
    assert (
        db_session.query(Generation)
        .filter(Generation.user_id == tenant["user"].id)
        .count()
        == 0
    )


def test_succeeded_request_cannot_be_overwritten_by_failure_path(db_session, user_factory):
    user = user_factory("no-overwrite@example.com")
    request = GenerationRequest(
        user_id=user.id,
        request_type="listing",
        idempotency_key=str(uuid.uuid4()),
        request_hash="hash",
        status=GenerationRequestStatus.SUCCEEDED,
        input={"name": "x"},
        response_payload={"title": "saved"},
    )
    db_session.add(request)
    db_session.commit()

    from app.services.generation_state import InvalidGenerationTransition, mark_failed

    with pytest.raises(InvalidGenerationTransition):
        mark_failed(request, error_code="X")


@pytest.mark.asyncio
async def test_failed_key_replay_does_not_call_llm(
    client,
    tenant_bundle,
    auth_and_idempotency,
    isolated_client_ip,
    valid_listing_payload,
    monkeypatch,
):
    tenant = tenant_bundle("fault-replay-failed")
    key = str(uuid.uuid4())
    calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            from app.core.exceptions import ai_response_invalid_exception

            raise ai_response_invalid_exception()
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 10
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    first = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_and_idempotency(tenant["user"], key),
            **isolated_client_ip("10.40.50.2"),
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert first.status_code == 502

    second = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_and_idempotency(tenant["user"], key),
            **isolated_client_ip("10.40.50.2"),
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert second.status_code == 409
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_tx2_proposal_flush_failure_rolls_back_entire_finalize(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.create_proposal_in_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("proposal flush failed")),
    )

    db = session_factory()
    try:
        with pytest.raises(AppException) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db.close()

    verify = session_factory()
    try:
        _assert_failed_cleanup(
            verify,
            user_id=user.id,
            idempotency_key=key,
            llm_calls=llm_calls["count"],
        )
        proposal_count = (
            verify.query(ListingProposal)
            .join(Product, ListingProposal.product_id == Product.id)
            .filter(Product.user_id == user.id)
            .count()
        )
        assert proposal_count == 0
        product = verify.query(Product).filter(Product.user_id == user.id).one_or_none()
        if product is not None:
            assert product.current_listing_version_id is None
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_tx2_commit_failure_leaves_no_proposal(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    original_finalize = GenerationExecutor._finalize_success

    def finalize_with_commit_failure(self, *args, **kwargs):
        self.db.commit = lambda: (_ for _ in ()).throw(SQLAlchemyError("tx2 commit failed"))
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "_finalize_success", finalize_with_commit_failure)

    db = session_factory()
    try:
        with pytest.raises(AppException):
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
    finally:
        db.close()

    verify = session_factory()
    try:
        assert llm_calls["count"] == 1
        record = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        proposal_count = (
            verify.query(ListingProposal)
            .filter(ListingProposal.generation_request_id == record.id)
            .count()
        )
        assert proposal_count == 0
        assert verify.query(Generation).filter(Generation.user_id == user.id).count() == 0
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_listing_finalize_locks_product_before_capturing_base(engine, monkeypatch):
    from sqlalchemy.exc import OperationalError

    import app.services.generation_executor as generation_executor_module

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, _request_hash, _canonical = _listing_fixture(session_factory)
    db = session_factory()
    try:
        product = Product(
            user_id=user.id,
            project_id=project.id,
            name="Lock Product",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        db.add(product)
        db.commit()
        db.refresh(product)
    finally:
        db.close()

    body.product_id = str(product.id)
    lock_state = {"nowait_failed": False}
    original_create = generation_executor_module.create_proposal_in_transaction

    def create_with_lock_check(db, **kwargs):
        locked_product = kwargs["product"]
        probe = session_factory()
        try:
            probe.query(Product).filter(Product.id == locked_product.id).with_for_update(
                nowait=True
            ).one()
        except OperationalError:
            lock_state["nowait_failed"] = True
        finally:
            probe.close()
        return original_create(db, **kwargs)

    monkeypatch.setattr(
        generation_executor_module,
        "create_proposal_in_transaction",
        create_with_lock_check,
    )

    async def fake_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    db = session_factory()
    try:
        await GenerationExecutor(db).execute_listing(
            user_id=str(user.id),
            body=body,
            idempotency_key=key,
            request_hash=canonical_request_hash(
                {
                    "project_id": str(project.id),
                    "product_id": str(product.id),
                    "name": body.name,
                    "category": body.category,
                    "market": body.market,
                    "platform": body.platform,
                    "target_customer": None,
                    "advantages": None,
                }
            ),
        )
    finally:
        db.close()

    assert lock_state["nowait_failed"] is True

    after = session_factory()
    try:
        after.query(Product).filter(Product.id == product.id).with_for_update(nowait=True).one()
        after.commit()
    finally:
        after.close()


@pytest.mark.asyncio
async def test_listing_finalize_uses_latest_committed_current_as_base(engine, monkeypatch):
    import asyncio
    import threading

    from app.services.listing_version import import_listing_version
    from tests.test_listing_versions import sample_listing_snapshot

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, _request_hash, _canonical = _listing_fixture(session_factory)
    setup = session_factory()
    try:
        product = Product(
            user_id=user.id,
            project_id=project.id,
            name="Base Product",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        setup.add(product)
        setup.flush()
        v1 = import_listing_version(
            setup,
            product_id=product.id,
            current_user_id=user.id,
            snapshot=sample_listing_snapshot(title="Version One"),
            idempotency_key=str(uuid.uuid4()),
            request_hash=str(uuid.uuid4()),
        )
        setup.commit()
        product_id = product.id
        v1_id = v1.version.id
    finally:
        setup.close()

    body.product_id = str(product_id)
    request_hash = canonical_request_hash(
        {
            "project_id": str(project.id),
            "product_id": str(product_id),
            "name": body.name,
            "category": body.category,
            "market": body.market,
            "platform": body.platform,
            "target_customer": None,
            "advantages": None,
        }
    )
    sync = {
        "ready_for_base_update": threading.Event(),
        "base_update_done": threading.Event(),
    }
    thread_errors: list[BaseException] = []
    original_finalize = GenerationExecutor._finalize_success

    def finalize_pause_before_product_lock(self, *args, **kwargs):
        if kwargs.get("listing_proposal_candidate") is not None:
            sync["ready_for_base_update"].set()
            if not sync["base_update_done"].wait(timeout=5):
                raise TimeoutError("timed out waiting for committed current update")
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "_finalize_success", finalize_pause_before_product_lock)

    async def fake_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)

    def run_finalize():
        db = session_factory()
        try:
            asyncio.run(
                GenerationExecutor(db).execute_listing(
                    user_id=str(user.id),
                    body=body,
                    idempotency_key=key,
                    request_hash=request_hash,
                )
            )
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    worker = threading.Thread(target=run_finalize)
    worker.start()
    assert sync["ready_for_base_update"].wait(timeout=5), "finalize should pause before product lock"

    update_session = session_factory()
    v2_id = None
    try:
        v2 = import_listing_version(
            update_session,
            product_id=product_id,
            current_user_id=user.id,
            snapshot=sample_listing_snapshot(title="Version Two"),
            idempotency_key=str(uuid.uuid4()),
            request_hash=str(uuid.uuid4()),
        )
        v2_id = v2.version.id
        assert v2_id != v1_id
        update_session.commit()
    finally:
        update_session.close()

    sync["base_update_done"].set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    if thread_errors:
        raise thread_errors[0]

    verify = session_factory()
    try:
        proposal = (
            verify.query(ListingProposal)
            .filter(ListingProposal.product_id == product_id)
            .one()
        )
        assert proposal.base_version_id == v2_id
        assert proposal.base_version_id != v1_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_proposal_finalize_failure_and_cleanup_failure_leaves_processing(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.create_proposal_in_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("proposal flush failed")),
    )
    monkeypatch.setattr(
        GenerationExecutor,
        "_attempt_finalize_failure_fresh",
        lambda *_args, **_kwargs: False,
    )

    db = session_factory()
    try:
        with pytest.raises(AppException) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db.close()

    verify = session_factory()
    try:
        assert llm_calls["count"] == 1
        row = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        assert row.status == GenerationRequestStatus.PROCESSING
        assert verify.query(Generation).filter(Generation.user_id == user.id).count() == 0
        assert (
            verify.query(ListingProposal)
            .join(Product, ListingProposal.product_id == Product.id)
            .filter(Product.user_id == user.id)
            .count()
            == 0
        )
        refreshed_user = verify.query(User).filter(User.id == user.id).one()
        assert refreshed_user.reserved_tokens > 0
        stale = find_stale_processing_requests(verify, older_than_minutes=0)
        assert any(item.id == row.id for item in stale)
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_listing_candidate_without_product_id_cannot_succeed(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def fake_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 20
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_listing)
    monkeypatch.setattr(
        "app.services.generation_executor.ProductService.resolve_or_create",
        lambda **_kwargs: None,
    )

    db = session_factory()
    try:
        with pytest.raises(AppException) as exc_info:
            await GenerationExecutor(db).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert exc_info.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db.close()

    verify = session_factory()
    try:
        assert llm_calls["count"] == 1
        record = (
            verify.query(GenerationRequest)
            .filter(GenerationRequest.idempotency_key == key)
            .one()
        )
        assert record.status == GenerationRequestStatus.FAILED
        assert record.error_code == GENERATION_FINALIZE_FAILED
        assert verify.query(Generation).filter(Generation.user_id == user.id).count() == 0
        assert (
            verify.query(ListingProposal)
            .join(Product, ListingProposal.product_id == Product.id)
            .filter(Product.user_id == user.id)
            .count()
            == 0
        )
        refreshed_user = verify.query(User).filter(User.id == user.id).one()
        assert refreshed_user.reserved_tokens == 0
    finally:
        verify.close()

    db2 = session_factory()
    try:
        with pytest.raises(AppException) as replay_exc:
            await GenerationExecutor(db2).execute_listing(
                user_id=str(user.id),
                body=body,
                idempotency_key=key,
                request_hash=request_hash,
            )
        assert llm_calls["count"] == 1
        assert replay_exc.value.error_code == GENERATION_FINALIZE_FAILED
    finally:
        db2.close()
