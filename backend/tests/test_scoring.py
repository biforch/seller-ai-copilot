from app.services.scoring import build_next_actions, compute_listing_score


def test_compute_listing_score_returns_expected_dimensions():
    result = compute_listing_score(
        {
            "title": "Premium Wireless Earbuds with Active Noise Cancellation and Long Battery",
            "bullets": [
                "Reduce ambient noise by 95% during calls",
                "Increase workout focus with secure fit",
                "Save time with 10-minute quick charge",
                "Improve comfort with 3 ear tip sizes",
                "Protect against sweat with IPX5 rating",
            ],
            "description": "<p>Order now to upgrade your daily commute.</p>" * 20,
            "keywords": [f"keyword-{index}" for index in range(10)],
        }
    )

    assert set(result.keys()) == {
        "overall",
        "title_seo",
        "keyword_coverage",
        "benefit_clarity",
        "conversion_potential",
    }
    assert 0 <= result["overall"] <= 100


def test_build_next_actions_suggests_missing_work():
    score = {
        "overall": 90,
        "title_seo": 90,
        "keyword_coverage": 60,
        "benefit_clarity": 90,
        "conversion_potential": 90,
    }
    actions = build_next_actions(score, {"listing": 1})
    titles = {action["title"] for action in actions}
    assert "Improve keywords" in titles
    assert "Analyze competitor reviews" in titles
    assert "Generate keywords" in titles
