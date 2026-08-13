"""Single source of truth for LLM token budgets used by OpenAI and quota estimation."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

PROMPTS_DIR = Path(__file__).parent

# Shared with OpenAIService._chat_json max_tokens per request type.
MAX_OUTPUT_TOKENS: dict[str, int] = {
    "listing": 2000,
    "analysis": 1000,
    "keywords": 800,
}

# Fixed system message bodies passed to _chat_json (must stay in sync with OpenAIService).
SYSTEM_PROMPT_TEXT: dict[str, str] = {
    "listing": (
        "You are an Amazon conversion optimization expert with 10+ years of experience.\n"
        "Your goal is to create product listings that improve CTR and conversion rate.\n"
        "Always output valid JSON."
    ),
    "analysis": (
        "You are a professional eCommerce analyst.\n"
        "Always output valid JSON."
    ),
    "keywords": (
        "You are an SEO keyword expert.\n"
        "Always output valid JSON."
    ),
}

_TEMPLATE_NAMES: dict[str, str] = {
    "listing": "listing",
    "analysis": "analyzer",
    "keywords": "keyword",
}

_CHARS_PER_TOKEN = 4
_SAFETY_MARGIN_TOKENS = 128


def _render_user_prompt(request_type: str, variables: dict) -> str:
    template_name = _TEMPLATE_NAMES[request_type]
    prompt_path = PROMPTS_DIR / f"{template_name}.txt"
    template = Template(
        prompt_path.read_text(encoding="utf-8"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return template.render(**variables)


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_rendered_input_tokens(request_type: str, render_variables: dict) -> int:
    """Estimate input tokens from rendered system + user prompts."""
    if request_type not in MAX_OUTPUT_TOKENS:
        raise ValueError(f"Unknown request_type: {request_type}")
    system = SYSTEM_PROMPT_TEXT[request_type]
    user = _render_user_prompt(request_type, render_variables)
    return _estimate_text_tokens(system) + _estimate_text_tokens(user)


def estimate_reserve_tokens(request_type: str, render_variables: dict) -> int:
    """Upper-bound reservation: rendered input + max output + safety margin."""
    rendered_input = estimate_rendered_input_tokens(request_type, render_variables)
    max_output = MAX_OUTPUT_TOKENS[request_type]
    return rendered_input + max_output + _SAFETY_MARGIN_TOKENS
