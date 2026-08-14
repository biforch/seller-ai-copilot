"""Orchestrates generation requests with idempotency, quota reservation, and state machine."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AI_PROVIDER_UNAVAILABLE,
    GENERATION_FINALIZE_FAILED,
    GENERATION_IN_PROGRESS,
    GENERATION_UNRECOVERABLE,
    IDEMPOTENCY_CONFLICT,
    AppException,
)
from app.core.orm_utils import orm_dict, orm_int, orm_optional_str, orm_str, orm_uuid
from app.core.payload_safety import prepare_request_input, prepare_response_payload
from app.database.session import SessionLocal
from app.models.generation import Generation
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.product import Product
from app.models.project import Project
from app.models.user import User
from app.prompts.versions import PROMPT_VERSIONS
from app.schemas.ai_output import ListingAIOutput
from app.schemas.listing import ListingSnapshot, listing_snapshot_from_ai_output
from app.services.analyzer import AnalyzerService
from app.services.generation_state import mark_failed, mark_succeeded
from app.services.listing_proposal import create_proposal_in_transaction, proposal_summary_dict
from app.services.openai import OpenAIService
from app.services.product import ProductService
from app.services.quota import (
    lock_user_for_quota,
    release_reserved_tokens,
    reserve_tokens,
    settle_reserved_to_consumed,
)
from app.services.quota_estimation import estimate_reserve_tokens
from app.services.scoring import compute_listing_score

logger = logging.getLogger(__name__)

STALE_PROCESSING_MINUTES = 30


class ExecutionPhase:
    BEFORE_LLM = "before_llm"
    LLM_IN_FLIGHT = "llm_in_flight"
    AFTER_LLM = "after_llm"
    FINALIZING = "finalizing"
    FINALIZED = "finalized"


@dataclass
class FinalizeOutcome:
    status: str
    payload: dict[str, Any] | None = None
    error_code: str | None = None


@dataclass
class ExecutionBeginResult:
    request: GenerationRequest
    replay: dict[str, Any] | None = None


@dataclass
class ExecutionContext:
    request_id: uuid.UUID
    user_id: uuid.UUID
    project: Project | None
    reserve_amount: int
    request_type: str


@dataclass
class ProductFinalizeArgs:
    user_id: str
    project_id: str
    product_id: str | None
    name: str
    category: str
    platform: str
    market: str
    target_customer: str | None
    advantages: list[str] | None


class GenerationExecutor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _load_existing_request(
        self,
        user_id: uuid.UUID,
        request_type: str,
        idempotency_key: str,
        *,
        db: Session | None = None,
    ) -> GenerationRequest | None:
        session = db or SessionLocal()
        own_session = db is None
        try:
            return (
                session.query(GenerationRequest)
                .filter(
                    GenerationRequest.user_id == user_id,
                    GenerationRequest.request_type == request_type,
                    GenerationRequest.idempotency_key == idempotency_key,
                )
                .first()
            )
        finally:
            if own_session:
                session.close()

    def _fetch_existing_after_conflict(
        self,
        user_id: uuid.UUID,
        request_type: str,
        idempotency_key: str,
    ) -> GenerationRequest | None:
        self.db.expire_all()
        return self._load_existing_request(
            user_id,
            request_type,
            idempotency_key,
            db=self.db,
        )

    def _get_user(self, user_id: str) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise AppException(message="User not found", code=status.HTTP_404_NOT_FOUND)
        return user

    def _get_project(self, project_id, user_id: uuid.UUID) -> Project | None:
        if not project_id:
            return None
        project = (
            self.db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )
        if not project:
            raise AppException(message="Project not found", code=status.HTTP_404_NOT_FOUND)
        return project

    def _resolve_context(
        self,
        user_id: uuid.UUID,
        product_id,
        target_customer: str | None,
        advantages: list[str] | None,
    ) -> tuple[str | None, list[str] | None]:
        if target_customer and advantages:
            return target_customer, advantages
        if not product_id:
            return target_customer, advantages
        existing = ProductService.get_by_id(self.db, str(product_id), str(user_id))
        if not existing:
            return target_customer, advantages
        tc = target_customer or orm_optional_str(existing.target_customer)
        adv = advantages
        if adv is None and existing.advantages is not None:
            adv = list(existing.advantages) if isinstance(existing.advantages, list) else None
        return tc, adv

    def _handle_existing_request(
        self,
        existing: GenerationRequest,
        *,
        request_hash: str,
    ) -> ExecutionBeginResult:
        if orm_str(existing.request_hash) != request_hash:
            raise AppException(
                message="Idempotency key reused with different payload",
                code=status.HTTP_409_CONFLICT,
                error_code=IDEMPOTENCY_CONFLICT,
            )

        if orm_str(existing.status) in {
            GenerationRequestStatus.PENDING,
            GenerationRequestStatus.PROCESSING,
        }:
            raise AppException(
                message="Generation already in progress",
                code=status.HTTP_409_CONFLICT,
                error_code=GENERATION_IN_PROGRESS,
            )

        if orm_str(existing.status) == GenerationRequestStatus.SUCCEEDED:
            payload = orm_dict(existing.response_payload)
            return ExecutionBeginResult(request=existing, replay=payload)

        if orm_str(existing.status) == GenerationRequestStatus.FAILED:
            raise AppException(
                message="Generation previously failed",
                code=status.HTTP_409_CONFLICT,
                error_code=orm_optional_str(existing.error_code) or "GENERATION_FAILED",
            )

        raise AppException(
            message="Unexpected generation request state",
            code=status.HTTP_409_CONFLICT,
        )

    def begin_execution(
        self,
        *,
        user_id: uuid.UUID,
        request_type: str,
        idempotency_key: str,
        request_hash: str,
        input_data: dict[str, Any],
        project_id=None,
    ) -> ExecutionBeginResult:
        existing = self._load_existing_request(
            user_id, request_type, idempotency_key, db=self.db
        )
        if existing is not None:
            return self._handle_existing_request(existing, request_hash=request_hash)

        safe_input = prepare_request_input(input_data)
        reserve_amount = estimate_reserve_tokens(request_type, safe_input)

        user = lock_user_for_quota(self.db, user_id)
        reserve_tokens(user, reserve_amount)

        request = GenerationRequest(
            user_id=user_id,
            request_type=request_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=GenerationRequestStatus.PROCESSING,
            project_id=project_id,
            input=safe_input,
            estimated_tokens=reserve_amount,
            reserved_tokens=reserve_amount,
            prompt_version=PROMPT_VERSIONS[request_type],
            started_at=datetime.utcnow(),
        )
        self.db.add(request)
        self.db.add(user)

        try:
            self.db.flush()
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            winner = self._fetch_existing_after_conflict(user_id, request_type, idempotency_key)
            if winner is None:
                winner = self._load_existing_request(user_id, request_type, idempotency_key)
            if winner is None:
                raise
            return self._handle_existing_request(winner, request_hash=request_hash)
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(request)
        self.db.refresh(user)
        return ExecutionBeginResult(request=request)

    def _read_request_outcome_fresh(self, request_id: uuid.UUID) -> FinalizeOutcome:
        db = SessionLocal()
        try:
            request = (
                db.query(GenerationRequest)
                .filter(GenerationRequest.id == request_id)
                .first()
            )
            if request is None:
                return FinalizeOutcome(status="missing")
            status_value = orm_str(request.status)
            if status_value == GenerationRequestStatus.SUCCEEDED:
                return FinalizeOutcome(
                    status="succeeded",
                    payload=orm_dict(request.response_payload),
                )
            if status_value == GenerationRequestStatus.FAILED:
                return FinalizeOutcome(
                    status="failed",
                    error_code=orm_optional_str(request.error_code) or "GENERATION_FAILED",
                )
            if status_value == GenerationRequestStatus.PROCESSING:
                return FinalizeOutcome(status="processing")
            return FinalizeOutcome(status="unknown")
        finally:
            db.close()

    def _attempt_finalize_failure_fresh(
        self,
        ctx: ExecutionContext,
        *,
        error_code: str,
        latency_ms: int | None = None,
        bill_tokens: int = 0,
    ) -> bool:
        """Best-effort failure cleanup in a fresh session. Returns True on success.

        Billing rule: for GENERATION_FINALIZE_FAILED, bill_tokens is always 0 —
        LLM may have returned usage, but we only release reserved quota and do not
        increase used_tokens when Tx2 did not commit. See backend/docs/quota-billing.md.
        """
        db = SessionLocal()
        try:
            user = lock_user_for_quota(db, ctx.user_id)
            request = (
                db.query(GenerationRequest)
                .filter(GenerationRequest.id == ctx.request_id)
                .with_for_update()
                .one()
            )
            if orm_str(request.status) != GenerationRequestStatus.PROCESSING:
                db.rollback()
                return True

            if bill_tokens > 0:
                settle_reserved_to_consumed(user, ctx.reserve_amount, bill_tokens)
            else:
                release_reserved_tokens(user, ctx.reserve_amount)

            mark_failed(
                request,
                error_code=error_code,
                latency_ms=latency_ms,
                tokens_used=bill_tokens if bill_tokens > 0 else 0,
                prompt_version=PROMPT_VERSIONS[ctx.request_type],
            )
            db.add(user)
            db.add(request)
            db.commit()
            return True
        except Exception:
            logger.critical(
                "Finalize failure cleanup failed request_id=%s error_code=%s",
                ctx.request_id,
                error_code,
                exc_info=True,
            )
            db.rollback()
            return False
        finally:
            db.close()

    def _resolve_post_llm_finalize_failure(
        self,
        ctx: ExecutionContext,
        exc: Exception,
        *,
        latency_ms: int,
    ) -> dict[str, Any]:
        """Read committed DB state after finalize failure and apply cleanup rules."""
        outcome = self._read_request_outcome_fresh(ctx.request_id)
        if outcome.status == "succeeded" and outcome.payload is not None:
            logger.info(
                "Finalize error but request already succeeded request_id=%s",
                ctx.request_id,
            )
            return outcome.payload

        if outcome.status == "failed":
            raise AppException(
                message="Generation previously failed",
                code=status.HTTP_409_CONFLICT,
                error_code=outcome.error_code or "GENERATION_FAILED",
            ) from exc

        if outcome.status == "processing":
            self._attempt_finalize_failure_fresh(
                ctx,
                error_code=GENERATION_FINALIZE_FAILED,
                latency_ms=latency_ms,
                bill_tokens=0,
            )
            raise AppException(
                message="Generation finalize failed",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=GENERATION_FINALIZE_FAILED,
                detail=str(exc) if settings.DEBUG else None,
                cause=exc,
            ) from exc

        if outcome.status == "missing":
            logger.critical(
                "Generation request missing after finalize error request_id=%s",
                ctx.request_id,
            )
            raise AppException(
                message="Generation state unrecoverable",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=GENERATION_UNRECOVERABLE,
                cause=exc,
            ) from exc

        raise AppException(
            message="Generation finalize failed",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=GENERATION_FINALIZE_FAILED,
            detail=str(exc) if settings.DEBUG else None,
            cause=exc,
        ) from exc

    def _handle_post_llm_error(
        self,
        ctx: ExecutionContext,
        exc: Exception,
        *,
        latency_ms: int,
    ) -> dict[str, Any]:
        try:
            self.db.rollback()
        except Exception:
            logger.debug("Rollback after finalize error failed request_id=%s", ctx.request_id)

        return self._resolve_post_llm_finalize_failure(ctx, exc, latency_ms=latency_ms)

    def _finalize_with_boundary(
        self,
        ctx: ExecutionContext,
        *,
        latency_ms: int,
        finalize_fn: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return finalize_fn()
        except AppException as exc:
            try:
                self.db.rollback()
            except Exception:
                pass
            return self._resolve_post_llm_finalize_failure(ctx, exc, latency_ms=latency_ms)
        except Exception as exc:
            return self._handle_post_llm_error(
                ctx,
                exc,
                latency_ms=latency_ms,
            )

    def _finalize_success(
        self,
        ctx: ExecutionContext,
        *,
        response_payload: dict[str, Any],
        model: str,
        tokens_used: int,
        latency_ms: int,
        generation_type: str,
        generation_input: dict[str, Any],
        generation_output: dict[str, Any],
        product_args: ProductFinalizeArgs | None = None,
        listing_proposal_candidate: ListingSnapshot | None = None,
    ) -> dict[str, Any]:
        safe_response = prepare_response_payload(response_payload)
        user = lock_user_for_quota(self.db, ctx.user_id)
        request = (
            self.db.query(GenerationRequest)
            .filter(GenerationRequest.id == ctx.request_id)
            .with_for_update()
            .one()
        )
        if orm_str(request.status) != GenerationRequestStatus.PROCESSING:
            if orm_str(request.status) == GenerationRequestStatus.SUCCEEDED:
                return orm_dict(request.response_payload)
            raise AppException(
                message="Generation state changed during execution",
                code=status.HTTP_409_CONFLICT,
                error_code=GENERATION_IN_PROGRESS,
            )

        product_id: uuid.UUID | None = None
        if product_args is not None:
            product_id = ProductService.resolve_or_create(
                db=self.db,
                user_id=product_args.user_id,
                project_id=product_args.project_id,
                product_id=product_args.product_id,
                name=product_args.name,
                category=product_args.category,
                platform=product_args.platform,
                market=product_args.market,
                target_customer=product_args.target_customer,
                advantages=product_args.advantages,
                commit=False,
            )
            if product_id is not None:
                safe_response["product_id"] = str(product_id)

        generation = Generation(
            user_id=ctx.user_id,
            project_id=ctx.project.id if ctx.project else None,
            product_id=product_id,
            type=generation_type,
            input=generation_input,
            output=generation_output,
            tokens_used=tokens_used,
        )
        self.db.add(generation)
        self.db.flush()

        settle_reserved_to_consumed(user, ctx.reserve_amount, tokens_used)

        request.generation_id = generation.id
        request.product_id = product_id

        if listing_proposal_candidate is not None:
            if product_id is None:
                raise AppException(
                    message="Product not found",
                    code=status.HTTP_404_NOT_FOUND,
                )
            product = (
                self.db.query(Product)
                .filter(Product.id == product_id, Product.user_id == ctx.user_id)
                .with_for_update()
                .one_or_none()
            )
            if product is None:
                raise AppException(
                    message="Product not found",
                    code=status.HTTP_404_NOT_FOUND,
                )
            proposal = create_proposal_in_transaction(
                self.db,
                product=product,
                generation_request=request,
                candidate=listing_proposal_candidate,
                allowed_statuses=frozenset({GenerationRequestStatus.PROCESSING}),
            )
            safe_response["proposal"] = proposal_summary_dict(proposal)

        mark_succeeded(
            request,
            response_payload=safe_response,
            generation_id=generation.id,
            model=model,
            prompt_version=PROMPT_VERSIONS[ctx.request_type],
            input_tokens=0,
            output_tokens=0,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
        self.db.add(user)
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return safe_response

    def _finalize_failure(
        self,
        ctx: ExecutionContext,
        *,
        error_code: str,
        latency_ms: int | None = None,
        bill_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        user = lock_user_for_quota(self.db, ctx.user_id)
        request = (
            self.db.query(GenerationRequest)
            .filter(GenerationRequest.id == ctx.request_id)
            .with_for_update()
            .one()
        )
        if orm_str(request.status) != GenerationRequestStatus.PROCESSING:
            return

        if bill_tokens > 0:
            settle_reserved_to_consumed(user, ctx.reserve_amount, bill_tokens)
        else:
            release_reserved_tokens(user, ctx.reserve_amount)

        mark_failed(
            request,
            error_code=error_code,
            latency_ms=latency_ms,
            tokens_used=bill_tokens,
            model=model,
            prompt_version=PROMPT_VERSIONS[ctx.request_type],
        )
        self.db.add(user)
        self.db.add(request)
        self.db.commit()

    async def _run_llm(
        self,
        ctx: ExecutionContext,
        llm_call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = await llm_call()
        except AppException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            error_code = exc.error_code or AI_PROVIDER_UNAVAILABLE
            self._finalize_failure(
                ctx,
                error_code=error_code,
                latency_ms=latency_ms,
                bill_tokens=0,
            )
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._finalize_failure(
                ctx,
                error_code=AI_PROVIDER_UNAVAILABLE,
                latency_ms=latency_ms,
                bill_tokens=0,
            )
            raise AppException(
                message="AI generation failed",
                code=status.HTTP_502_BAD_GATEWAY,
                error_code=AI_PROVIDER_UNAVAILABLE,
                detail=str(exc) if settings.DEBUG else None,
                cause=exc,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        result["_latency_ms"] = latency_ms
        return result

    async def execute_listing(
        self,
        *,
        user_id: str,
        body,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        user = self._get_user(user_id)
        user_uuid = orm_uuid(user.id)
        project = self._get_project(body.project_id, user_uuid)
        target_customer, advantages = self._resolve_context(
            user_uuid,
            body.product_id,
            body.target_customer,
            body.advantages,
        )

        canonical_input = {
            "project_id": str(body.project_id) if body.project_id else None,
            "product_id": str(body.product_id) if body.product_id else None,
            "name": body.name,
            "category": body.category,
            "market": body.market,
            "platform": body.platform,
            "target_customer": target_customer,
            "advantages": advantages,
        }

        begin = self.begin_execution(
            user_id=user_uuid,
            request_type="listing",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id if project else None,
        )
        if begin.replay is not None:
            return begin.replay

        ctx = ExecutionContext(
            request_id=orm_uuid(begin.request.id),
            user_id=user_uuid,
            project=project,
            reserve_amount=orm_int(begin.request.reserved_tokens),
            request_type="listing",
        )

        ai_service = OpenAIService()
        project_goal = orm_optional_str(project.description) if project else None

        async def call_llm() -> dict[str, Any]:
            return await ai_service.generate_listing(
                product_name=body.name,
                category=body.category,
                market=body.market,
                platform=body.platform,
                project_goal=project_goal,
                target_customer=target_customer,
                advantages=advantages,
                request_id=str(begin.request.id),
            )

        result = await self._run_llm(ctx, call_llm)
        tokens_used = int(result.get("tokens_used", 0))
        latency_ms = int(result.pop("_latency_ms", 0))

        def finalize_listing() -> dict[str, Any]:
            ai_output = ListingAIOutput.model_validate(
                {
                    "title": result["title"],
                    "bullets": result["bullets"],
                    "description": result["description"],
                    "keywords": result["keywords"],
                }
            )
            candidate = listing_snapshot_from_ai_output(ai_output)
            score = compute_listing_score(result)
            result_with_score = {**result, "score": score}
            response_payload = {
                "project_id": str(project.id) if project else None,
                "title": result.get("title", ""),
                "bullets": result.get("bullets", []),
                "description": result.get("description", ""),
                "keywords": result.get("keywords", []),
                "score": score,
                "tokens_used": tokens_used,
            }
            product_args = None
            if project is not None:
                product_args = ProductFinalizeArgs(
                    user_id=str(user.id),
                    project_id=str(project.id),
                    product_id=str(body.product_id) if body.product_id else None,
                    name=body.name,
                    category=body.category,
                    platform=body.platform,
                    market=body.market,
                    target_customer=target_customer,
                    advantages=advantages,
                )
            return self._finalize_success(
                ctx,
                response_payload=response_payload,
                model=ai_service.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                generation_type="listing",
                generation_input={
                    "name": body.name,
                    "category": body.category,
                    "market": body.market,
                    "platform": body.platform,
                },
                generation_output=result_with_score,
                product_args=product_args,
                listing_proposal_candidate=candidate,
            )

        return self._finalize_with_boundary(
            ctx,
            latency_ms=latency_ms,
            finalize_fn=finalize_listing,
        )

    async def execute_analyze(
        self,
        *,
        user_id: str,
        body,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        user = self._get_user(user_id)
        user_uuid = orm_uuid(user.id)
        project = self._get_project(body.project_id, user_uuid)

        canonical_input = {
            "project_id": str(body.project_id) if body.project_id else None,
            "title": body.title,
            "reviews": body.reviews,
            "rating": body.rating,
            "description": body.description,
        }

        begin = self.begin_execution(
            user_id=user_uuid,
            request_type="analysis",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id if project else None,
        )
        if begin.replay is not None:
            return begin.replay

        ctx = ExecutionContext(
            request_id=orm_uuid(begin.request.id),
            user_id=user_uuid,
            project=project,
            reserve_amount=orm_int(begin.request.reserved_tokens),
            request_type="analysis",
        )

        analyzer = AnalyzerService()

        async def call_llm() -> dict[str, Any]:
            return await analyzer.analyze_listing(
                title=body.title,
                reviews=body.reviews,
                rating=body.rating,
                description=body.description,
            )

        result = await self._run_llm(ctx, call_llm)
        tokens_used = int(result.get("tokens_used", 0))
        latency_ms = int(result.pop("_latency_ms", 0))

        def finalize_analysis() -> dict[str, Any]:
            response_payload = {
                **result,
                "project_id": str(project.id) if project else None,
                "tokens_used": tokens_used,
            }
            return self._finalize_success(
                ctx,
                response_payload=response_payload,
                model=OpenAIService().model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                generation_type="analysis",
                generation_input=canonical_input,
                generation_output=result,
            )

        return self._finalize_with_boundary(
            ctx,
            latency_ms=latency_ms,
            finalize_fn=finalize_analysis,
        )

    async def execute_keywords(
        self,
        *,
        user_id: str,
        body,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        user = self._get_user(user_id)
        user_uuid = orm_uuid(user.id)
        project = self._get_project(body.project_id, user_uuid)
        target_customer, advantages = self._resolve_context(
            user_uuid,
            body.product_id,
            body.target_customer,
            body.advantages,
        )

        canonical_input = {
            "project_id": str(body.project_id) if body.project_id else None,
            "product_id": str(body.product_id) if body.product_id else None,
            "name": body.name,
            "category": body.category,
            "market": body.market,
            "platform": body.platform,
            "target_customer": target_customer,
            "advantages": advantages,
        }

        begin = self.begin_execution(
            user_id=user_uuid,
            request_type="keywords",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            input_data=canonical_input,
            project_id=project.id if project else None,
        )
        if begin.replay is not None:
            return begin.replay

        ctx = ExecutionContext(
            request_id=orm_uuid(begin.request.id),
            user_id=user_uuid,
            project=project,
            reserve_amount=orm_int(begin.request.reserved_tokens),
            request_type="keywords",
        )

        ai_service = OpenAIService()

        async def call_llm() -> dict[str, Any]:
            return await ai_service.generate_keywords(
                product_name=body.name,
                category=body.category,
                market=body.market,
                target_customer=target_customer,
                advantages=advantages,
                request_id=str(begin.request.id),
            )

        result = await self._run_llm(ctx, call_llm)
        tokens_used = int(result.get("tokens_used", 0))
        latency_ms = int(result.pop("_latency_ms", 0))

        def finalize_keywords() -> dict[str, Any]:
            response_payload = {
                **result,
                "project_id": str(project.id) if project else None,
                "product_id": str(body.product_id) if body.product_id else None,
                "tokens_used": tokens_used,
            }
            product_args = None
            if project is not None:
                product_args = ProductFinalizeArgs(
                    user_id=str(user.id),
                    project_id=str(project.id),
                    product_id=str(body.product_id) if body.product_id else None,
                    name=body.name,
                    category=body.category,
                    platform=body.platform,
                    market=body.market,
                    target_customer=target_customer,
                    advantages=advantages,
                )
            return self._finalize_success(
                ctx,
                response_payload=response_payload,
                model=ai_service.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                generation_type="keywords",
                generation_input={
                    "name": body.name,
                    "category": body.category,
                    "market": body.market,
                },
                generation_output=result,
                product_args=product_args,
            )

        return self._finalize_with_boundary(
            ctx,
            latency_ms=latency_ms,
            finalize_fn=finalize_keywords,
        )


def find_stale_processing_requests(
    db: Session,
    *,
    older_than_minutes: int = STALE_PROCESSING_MINUTES,
) -> list[GenerationRequest]:
    cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
    return (
        db.query(GenerationRequest)
        .filter(
            GenerationRequest.status == GenerationRequestStatus.PROCESSING,
            GenerationRequest.started_at.isnot(None),
            GenerationRequest.started_at < cutoff,
        )
        .all()
    )
