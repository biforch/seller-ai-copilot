"""Canonical valid LLM output fixtures aligned with prompts and schemas."""

VALID_LISTING_OUTPUT = {
    "title": "Premium Wireless Earbuds with Active Noise Cancellation",
    "bullets": [
        "Blocks ambient noise for focused listening during commutes",
        "Long battery life with quick charging for all-day use",
        "IPX5 sweat resistance for workouts and outdoor use",
        "Stable Bluetooth connection for reliable daily pairing",
        "Includes multiple ear tip sizes for secure comfortable fit",
    ],
    "description": "<p>Experience clear audio and all-day comfort.</p>",
    "keywords": [
        "wireless earbuds",
        "noise cancelling earbuds",
        "bluetooth earbuds",
        "workout earbuds",
        "long battery earbuds",
        "ipx5 earbuds",
        "premium earbuds",
        "in ear headphones",
        "travel earbuds",
        "android earbuds",
    ],
}

VALID_ANALYZE_OUTPUT = {
    "strengths": [
        "Clear product positioning in the title",
        "Strong social proof from review volume",
        "Description highlights core use cases",
    ],
    "weaknesses": [
        "Title may be too generic for niche searches",
        "Description lacks structured benefit bullets",
        "Limited keyword coverage in visible copy",
    ],
    "opportunities": [
        "noise cancelling earbuds",
        "wireless workout earbuds",
        "long battery earbuds",
    ],
}

VALID_KEYWORDS_OUTPUT = {
    "keywords": [
        f"wireless earbuds keyword {index}"
        for index in range(1, 16)
    ],
    "primary_keyword": "wireless noise cancelling earbuds",
    "search_intent": "Shoppers comparing wireless earbuds for commuting and workouts",
}
