"""Deterministic score calculation for Listing Audit reports."""

from __future__ import annotations

from app.analysis.schemas import DimensionScores

SCORE_WEIGHTS: dict[str, float] = {
    "positioning": 0.20,
    "buyer_clarity": 0.20,
    "information_quality": 0.20,
    "conversion_readiness": 0.25,
    "discoverability": 0.15,
}


def calculate_overall_score(scores: DimensionScores) -> int:
    """Return the confirmed weighted score using round-half-up semantics."""
    raw = sum(getattr(scores, name).score * weight for name, weight in SCORE_WEIGHTS.items())
    return int(raw + 0.5)
