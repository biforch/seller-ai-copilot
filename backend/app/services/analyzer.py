from typing import Any, Dict

from app.services.openai import OpenAIService


class AnalyzerService:
    """竞品分析服务."""

    def __init__(self) -> None:
        self._ai = OpenAIService()


    async def analyze_listing(
        self,
        title: str,
        reviews: int,
        rating: float,
        description: str,
    ) -> Dict[str, Any]:

        result = await self._ai.analyze_listing(
            title=title,
            reviews=reviews,
            rating=rating,
            description=description,
        )

        return result