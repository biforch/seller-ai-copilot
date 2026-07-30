import json
import logging
import time
from pathlib import Path
from typing import Any, Dict

from jinja2 import Template
from openai import AsyncOpenAI

from app.core.config import settings


logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class OpenAIService:
    """
    AI 服务封装
    支持 OpenAI / OpenRouter
    """

    def __init__(self) -> None:

        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,

            default_headers={
                "HTTP-Referer": settings.OPENAI_REFERER,
                "X-Title": settings.OPENAI_TITLE,
            },

            timeout=settings.OPENAI_TIMEOUT,
            max_retries=2,
        )


        self.model = settings.OPENAI_MODEL

        self.fallback_models = (
            settings.OPENAI_FALLBACK_MODELS.split(",")
            if settings.OPENAI_FALLBACK_MODELS
            else []
        )


    def _render_prompt(
        self,
        template_name: str,
        **variables: Any,
    ) -> str:

        prompt_path = (
            PROMPTS_DIR /
            f"{template_name}.txt"
        )


        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt template not found: {template_name}.txt"
            )


        template = Template(
            prompt_path.read_text(
                encoding="utf-8"
            ),
            trim_blocks=True,
            lstrip_blocks=True,
        )


        return template.render(**variables)



    async def _chat_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:


        models = [
            self.model,
            *self.fallback_models,
        ]


        last_error = None


        for model in models:

            start = time.time()


            try:

                logger.info(
                    "AI request model=%s",
                    model
                )


                response = await self.client.chat.completions.create(

                    model=model,

                    messages=[
                        {
                            "role": "system",
                            "content": system,
                        },
                        {
                            "role": "user",
                            "content": user,
                        }
                    ],

                    temperature=0.7,

                    max_tokens=max_tokens,

                    response_format={
                        "type": "json_object"
                    },
                )


                content = (
                    response
                    .choices[0]
                    .message
                    .content
                )


                if not content:
                    raise Exception(
                        "AI returned empty response"
                    )


                try:

                    result = json.loads(content)

                except json.JSONDecodeError:

                    logger.error(
                        "Invalid JSON:%s",
                        content
                    )

                    raise Exception(
                        "AI response invalid JSON"
                    )


                # 保存真实token消耗
                result["tokens_used"] = (
                    response
                    .usage
                    .total_tokens
                    if response.usage
                    else 0
                )


                logger.info(
                    "AI success model=%s cost_time=%.2fs tokens=%s",
                    model,
                    time.time()-start,
                    result["tokens_used"]
                )


                return result


            except Exception as e:

                last_error = e


                logger.warning(
                    "AI model failed %s: %s",
                    model,
                    str(e)
                )


        raise last_error



    async def generate_listing(
        self,
        product_name: str,
        category: str,
        market: str,
        platform: str,
        project_goal: str = None,
        target_customer: str = None,
        advantages: list = None,
    ) -> Dict[str, Any]:


        prompt = self._render_prompt(
            "listing",
            product_name=product_name,
            category=category,
            market=market,
            platform=platform,
            project_goal=project_goal,
            target_customer=target_customer,
            advantages=advantages or [],
        )


        return await self._chat_json(
            """
You are an Amazon conversion optimization expert with 10+ years of experience.
Your goal is to create product listings that improve CTR and conversion rate.
Always output valid JSON.
""",
            prompt,
        )



    async def analyze_listing(
        self,
        title: str,
        reviews: int,
        rating: float,
        description: str,
    ) -> Dict[str, Any]:


        prompt = self._render_prompt(
            "analyzer",
            title=title,
            reviews=reviews,
            rating=rating,
            description=description,
        )


        return await self._chat_json(
            """
You are a professional eCommerce analyst.
Always output valid JSON.
""",
            prompt,
            max_tokens=1000,
        )



    async def generate_keywords(
        self,
        product_name: str,
        category: str,
        market: str,
        target_customer: str = None,
        advantages: list = None,
    ) -> Dict[str, Any]:


        prompt = self._render_prompt(
            "keyword",
            product_name=product_name,
            category=category,
            market=market,
            target_customer=target_customer,
            advantages=advantages or [],
        )


        return await self._chat_json(
            """
You are an SEO keyword expert.
Always output valid JSON.
""",
            prompt,
            max_tokens=800,
        )