"""Stable prompt version identifiers — increment when template content changes."""

PROMPT_VERSION_LISTING = "listing-v2"
PROMPT_VERSION_ANALYSIS = "analysis-v1"
PROMPT_VERSION_KEYWORDS = "keywords-v1"

PROMPT_VERSIONS: dict[str, str] = {
    "listing": PROMPT_VERSION_LISTING,
    "analysis": PROMPT_VERSION_ANALYSIS,
    "keywords": PROMPT_VERSION_KEYWORDS,
}
