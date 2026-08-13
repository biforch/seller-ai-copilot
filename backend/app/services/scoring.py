"""
Product Score + AI Next Action.

这些是启发式规则，直接从最新一次 Listing 生成结果中计算，
不额外调用 AI（不产生额外 token 成本）。
未来可以升级为让 AI 自己评分（额外一次调用），
但目前先用规则打分，保证稳定、免费、可解释。
"""

from typing import Any

BENEFIT_WORDS = [
    "improve",
    "reduce",
    "increase",
    "save",
    "enhance",
    "boost",
    "eliminate",
    "prevent",
    "protect",
    "comfort",
    "durable",
    "lightweight",
    "fast",
    "easy",
    "effortless",
    "long-lasting",
]


CTA_PHRASES = [
    "order now",
    "buy now",
    "add to cart",
    "don't wait",
    "upgrade your",
    "experience the",
    "get yours",
]


def _score_title(title: str) -> int:

    length = len(title or "")

    if 80 <= length <= 200:

        return 90

    if 50 <= length < 80 or 200 < length <= 230:

        return 75

    if length == 0:

        return 0

    return 55


def _score_keyword_coverage(
    keywords: list[str],
    target: int = 10,
) -> int:

    if not target:

        return 0

    return min(
        100,
        round(len(keywords or []) / target * 100),
    )


def _score_bullet(bullet: str) -> int:

    text = (bullet or "").lower()

    has_number = any(ch.isdigit() for ch in bullet or "")

    has_benefit_word = any(
        word in text for word in BENEFIT_WORDS
    )

    if has_number and has_benefit_word:

        return 100

    if has_number or has_benefit_word:

        return 75

    return 50


def _score_benefit_clarity(
    bullets: list[str],
) -> int:

    if not bullets:

        return 0

    return round(
        sum(_score_bullet(b) for b in bullets) / len(bullets)
    )


def _score_conversion_potential(
    description: str,
) -> int:

    description = description or ""

    score = 55

    if len(description) > 300:

        score += 15

    if "<" in description and ">" in description:

        score += 10

    if any(
        phrase in description.lower()
        for phrase in CTA_PHRASES
    ):

        score += 20

    return min(100, score)


def compute_listing_score(
    result: dict[str, Any],
    target_keyword_count: int = 10,
) -> dict[str, int]:
    """
    从一次 Listing 生成结果计算质量评分。
    result 需要包含 title / bullets / description / keywords。
    """

    title_seo = _score_title(
        result.get("title", "")
    )

    keyword_coverage = _score_keyword_coverage(
        result.get("keywords", []),
        target_keyword_count,
    )

    benefit_clarity = _score_benefit_clarity(
        result.get("bullets", [])
    )

    conversion_potential = _score_conversion_potential(
        result.get("description", "")
    )

    overall = round(
        (
            title_seo
            + keyword_coverage
            + benefit_clarity
            + conversion_potential
        )
        / 4
    )

    return {
        "overall": overall,
        "title_seo": title_seo,
        "keyword_coverage": keyword_coverage,
        "benefit_clarity": benefit_clarity,
        "conversion_potential": conversion_potential,
    }


def build_next_actions(
    score: dict[str, int] | None,
    generation_type_counts: dict[str, int],
) -> list[dict[str, str]]:
    """
    根据评分短板 + 缺失的生成类型，给出下一步建议。
    """

    actions: list[dict[str, str]] = []


    if score:

        if score["keyword_coverage"] < 80:

            actions.append({
                "title": "Improve keywords",
                "reason": "Low search coverage",
            })

        if score["title_seo"] < 80:

            actions.append({
                "title": "Rewrite title",
                "reason": "Title length or structure may hurt SEO",
            })

        if score["benefit_clarity"] < 80:

            actions.append({
                "title": "Strengthen bullet benefits",
                "reason": "Bullets lack measurable, benefit-driven language",
            })

        if score["conversion_potential"] < 80:

            actions.append({
                "title": "Enhance description",
                "reason": "Description could be more conversion-focused",
            })


    if not generation_type_counts.get("analysis"):

        actions.append({
            "title": "Analyze competitor reviews",
            "reason": "No competitor analysis yet",
        })

    if not generation_type_counts.get("keywords"):

        actions.append({
            "title": "Generate keywords",
            "reason": "No dedicated keyword research yet",
        })


    if not actions:

        actions.append({
            "title": "Keep optimizing",
            "reason": "Listing is performing well — consider testing variations",
        })


    return actions[:5]
