"""Centralized generation request status transitions."""

from __future__ import annotations

from datetime import datetime

from fastapi import status

from app.core.exceptions import AppException
from app.core.orm_utils import orm_str
from app.models.generation_request import GenerationRequest, GenerationRequestStatus

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    GenerationRequestStatus.PENDING: frozenset({GenerationRequestStatus.PROCESSING}),
    GenerationRequestStatus.PROCESSING: frozenset(
        {GenerationRequestStatus.SUCCEEDED, GenerationRequestStatus.FAILED}
    ),
    GenerationRequestStatus.SUCCEEDED: frozenset(),
    GenerationRequestStatus.FAILED: frozenset(),
}


class InvalidGenerationTransition(AppException):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            message="Invalid generation state transition",
            code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition from {current!r} to {target!r}",
        )


def assert_can_transition(current: str, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidGenerationTransition(current, target)


def mark_processing(request: GenerationRequest, *, started_at: datetime | None = None) -> None:
    current = orm_str(request.status)
    assert_can_transition(current, GenerationRequestStatus.PROCESSING)
    request.status = GenerationRequestStatus.PROCESSING
    request.started_at = started_at or datetime.utcnow()


def mark_succeeded(
    request: GenerationRequest,
    *,
    response_payload: dict,
    generation_id,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    tokens_used: int,
    latency_ms: int,
    completed_at: datetime | None = None,
) -> None:
    current = orm_str(request.status)
    assert_can_transition(current, GenerationRequestStatus.SUCCEEDED)
    request.status = GenerationRequestStatus.SUCCEEDED
    request.response_payload = response_payload
    request.generation_id = generation_id
    request.model = model
    request.prompt_version = prompt_version
    request.input_tokens = input_tokens
    request.output_tokens = output_tokens
    request.tokens_used = tokens_used
    request.latency_ms = latency_ms
    request.error_code = None
    request.completed_at = completed_at or datetime.utcnow()


def mark_failed(
    request: GenerationRequest,
    *,
    error_code: str,
    latency_ms: int | None = None,
    tokens_used: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
    prompt_version: str | None = None,
    completed_at: datetime | None = None,
) -> None:
    current = orm_str(request.status)
    assert_can_transition(current, GenerationRequestStatus.FAILED)
    request.status = GenerationRequestStatus.FAILED
    request.error_code = error_code
    request.latency_ms = latency_ms
    request.tokens_used = tokens_used
    request.input_tokens = input_tokens
    request.output_tokens = output_tokens
    request.model = model
    request.prompt_version = prompt_version
    request.completed_at = completed_at or datetime.utcnow()
