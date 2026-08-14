"""Pure functions for listing diff and final snapshot computation."""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.exceptions import (
    LISTING_DECISIONS_INCOMPLETE,
    LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
    AppException,
)
from app.schemas.listing import FieldDecisions, ListingSnapshot, listing_snapshot_from_dict


def _normalize_snapshot(snapshot: ListingSnapshot) -> ListingSnapshot:
    return listing_snapshot_from_dict(snapshot.canonical_dict())


def _field_changed(base_value: Any, candidate_value: Any) -> bool:
    if isinstance(base_value, list) and isinstance(candidate_value, list):
        return base_value != candidate_value
    return base_value != candidate_value


def build_listing_diff(
    base: ListingSnapshot | None,
    candidate: ListingSnapshot,
) -> dict[str, dict[str, Any]]:
    """Return per-field base/candidate/changed comparison."""
    normalized_candidate = _normalize_snapshot(candidate)
    result: dict[str, dict[str, Any]] = {}

    if base is None:
        for field_name in ("title", "bullets", "description", "backend_keywords"):
            candidate_value = getattr(normalized_candidate, field_name)
            result[field_name] = {
                "base": None,
                "candidate": candidate_value,
                "changed": True,
            }
        return result

    normalized_base = _normalize_snapshot(base)
    for field_name in ("title", "bullets", "description", "backend_keywords"):
        base_value = getattr(normalized_base, field_name)
        candidate_value = getattr(normalized_candidate, field_name)
        result[field_name] = {
            "base": base_value,
            "candidate": candidate_value,
            "changed": _field_changed(base_value, candidate_value),
        }
    return result


def compute_final_snapshot(
    base: ListingSnapshot | None,
    candidate: ListingSnapshot,
    decisions: FieldDecisions,
) -> ListingSnapshot:
    """Merge base and candidate according to review decisions."""
    normalized_candidate = _normalize_snapshot(candidate)

    if base is None:
        if decisions.has_pending() or any(
            getattr(decisions, field_name) == "reject"
            for field_name in ("title", "bullets", "description", "backend_keywords")
        ):
            raise AppException(
                message="Partial accept is forbidden without a base version",
                code=status.HTTP_409_CONFLICT,
                error_code=LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
            )
        return normalized_candidate

    if decisions.has_pending():
        raise AppException(
            message="All field decisions must be resolved before approval",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_DECISIONS_INCOMPLETE,
        )

    normalized_base = _normalize_snapshot(base)
    merged: dict[str, Any] = {}
    for field_name in ("title", "bullets", "description", "backend_keywords"):
        decision = getattr(decisions, field_name)
        if decision == "accept":
            merged[field_name] = getattr(normalized_candidate, field_name)
        elif decision == "reject":
            merged[field_name] = getattr(normalized_base, field_name)
        else:
            raise AppException(
                message="All field decisions must be resolved before approval",
                code=status.HTTP_409_CONFLICT,
                error_code=LISTING_DECISIONS_INCOMPLETE,
            )

    return listing_snapshot_from_dict(merged)
