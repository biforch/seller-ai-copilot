import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from jinja2 import Template
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.exceptions import AI_PROVIDER_UNAVAILABLE, AppException, ai_response_invalid_exception
from app.prompts.token_budget import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT_TEXT
from app.schemas.ai_output import AnalyzeAIOutput, KeywordsAIOutput, ListingAIOutput

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class OpenAIService:
    """AI 服务封装，支持 OpenAI / OpenRouter。"""

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

    def _render_prompt(self, template_name: str, **variables: Any) -> str:
        prompt_path = PROMPTS_DIR / f"{template_name}.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_name}.txt")

        template = Template(
            prompt_path.read_text(encoding="utf-8"),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        return template.render(**variables)

    def _validate_ai_payload(
        self,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        *,
        model: str,
        request_id: str,
    ) -> dict[str, Any]:
        try:
            validated = schema.model_validate(payload)
        except ValidationError as exc:
            summary = "; ".join(
                f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
                for err in exc.errors()[:5]
            )
            logger.warning(
                "AI output validation failed request_id=%s model=%s schema=%s errors=%s",
                request_id,
                model,
                schema_name,
                summary,
            )
            raise ai_response_invalid_exception(exc) from exc
        return validated.model_dump()

    async def _chat_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        schema_name: str,
        max_tokens: int = 2000,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        models = [self.model, *self.fallback_models]
        correlation_id = request_id or str(uuid.uuid4())
        last_error: Exception | None = None

        for model in models:
            start = time.time()
            try:
                logger.info(
                    "AI request request_id=%s model=%s schema=%s",
                    correlation_id,
                    model,
                    schema_name,
                )

                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.7,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                if not content:
                    raise ai_response_invalid_exception()

                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "AI output JSON decode failed request_id=%s model=%s schema=%s",
                        correlation_id,
                        model,
                        schema_name,
                    )
                    raise ai_response_invalid_exception(exc) from exc

                if not isinstance(parsed, dict):
                    logger.warning(
                        "AI output not an object request_id=%s model=%s schema=%s",
                        correlation_id,
                        model,
                        schema_name,
                    )
                    raise ai_response_invalid_exception()

                result = self._validate_ai_payload(
                    parsed,
                    schema,
                    schema_name,
                    model=model,
                    request_id=correlation_id,
                )

                result["tokens_used"] = (
                    response.usage.total_tokens if response.usage else 0
                )

                logger.info(
                    "AI success request_id=%s model=%s schema=%s latency_s=%.2f tokens=%s",
                    correlation_id,
                    model,
                    schema_name,
                    time.time() - start,
                    result["tokens_used"],
                )
                return result

            except AppException:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "AI model failed request_id=%s model=%s error=%s",
                    correlation_id,
                    model,
                    type(exc).__name__,
                )

        if isinstance(last_error, AppException):
            raise last_error

        raise AppException(
            message="AI generation failed",
            code=502,
            detail="The AI service is temporarily unavailable.",
            error_code=AI_PROVIDER_UNAVAILABLE,
        ) from last_error

    async def generate_listing(
        self,
        product_name: str,
        category: str,
        market: str,
        platform: str,
        project_goal: str | None = None,
        target_customer: str | None = None,
        advantages: list | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
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
            SYSTEM_PROMPT_TEXT["listing"],
            prompt,
            ListingAIOutput,
            "ListingAIOutput",
            max_tokens=MAX_OUTPUT_TOKENS["listing"],
            request_id=request_id,
        )

    async def analyze_listing(
        self,
        title: str,
        reviews: int,
        rating: float,
        description: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        prompt = self._render_prompt(
            "analyzer",
            title=title,
            reviews=reviews,
            rating=rating,
            description=description,
        )

        return await self._chat_json(
            SYSTEM_PROMPT_TEXT["analysis"],
            prompt,
            AnalyzeAIOutput,
            "AnalyzeAIOutput",
            max_tokens=MAX_OUTPUT_TOKENS["analysis"],
            request_id=request_id,
        )

    async def generate_keywords(
        self,
        product_name: str,
        category: str,
        market: str,
        target_customer: str | None = None,
        advantages: list | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        prompt = self._render_prompt(
            "keyword",
            product_name=product_name,
            category=category,
            market=market,
            target_customer=target_customer,
            advantages=advantages or [],
        )

        return await self._chat_json(
            SYSTEM_PROMPT_TEXT["keywords"],
            prompt,
            KeywordsAIOutput,
            "KeywordsAIOutput",
            max_tokens=MAX_OUTPUT_TOKENS["keywords"],
            request_id=request_id,
        )
