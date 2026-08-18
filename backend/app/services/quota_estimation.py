"""Token-based quota reservation estimates — delegates to prompt token_budget."""

from __future__ import annotations

from app.prompts.token_budget import estimate_reserve_tokens as _estimate_reserve_tokens
from app.prompts.versions import PROMPT_VERSIONS

# Re-export for callers; render_variables shape depends on request_type.
__all__ = ["estimate_reserve_tokens", "listing_render_variables", "analysis_render_variables", "keywords_render_variables"]


def listing_render_variables(canonical_input: dict) -> dict:
    return {
        "product_name": canonical_input.get("name") or "",
        "category": canonical_input.get("category") or "",
        "market": canonical_input.get("market") or "",
        "platform": canonical_input.get("platform") or "",
        "project_goal": None,
        "target_customer": canonical_input.get("target_customer"),
        "advantages": canonical_input.get("advantages") or [],
        "amazon_catalog_context": canonical_input.get("amazon_catalog_context"),
    }


def analysis_render_variables(canonical_input: dict) -> dict:
    return {
        "title": canonical_input.get("title") or "",
        "reviews": canonical_input.get("reviews") or 0,
        "rating": canonical_input.get("rating") or 0.0,
        "description": canonical_input.get("description") or "",
    }


def keywords_render_variables(canonical_input: dict) -> dict:
    return {
        "product_name": canonical_input.get("name") or "",
        "category": canonical_input.get("category") or "",
        "market": canonical_input.get("market") or "",
        "target_customer": canonical_input.get("target_customer"),
        "advantages": canonical_input.get("advantages") or [],
    }


_RENDER_BUILDERS = {
    "listing": listing_render_variables,
    "analysis": analysis_render_variables,
    "keywords": keywords_render_variables,
}


def estimate_reserve_tokens(request_type: str, canonical_input: dict) -> int:
    if request_type not in PROMPT_VERSIONS:
        raise ValueError(f"Unknown request_type: {request_type}")
    builder = _RENDER_BUILDERS[request_type]
    return _estimate_reserve_tokens(request_type, builder(canonical_input))
