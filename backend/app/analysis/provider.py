"""Production provider adapter for the internal Listing Audit path."""

from __future__ import annotations

import json
import uuid

from openai import AsyncOpenAI

from app.analysis.prompt import ListingAuditPrompt
from app.analysis.schemas import ListingAuditLLMOutput
from app.analysis.service import ListingAuditProviderResponse
from app.core.config import settings
from app.core.exceptions import AI_PROVIDER_UNAVAILABLE, AppException, ai_response_invalid_exception
from app.prompts.token_budget import MAX_OUTPUT_TOKENS


class OpenAIListingAuditProvider:
    def __init__(self) -> None:
        self.model = settings.OPENAI_MODEL
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            default_headers={
                "HTTP-Referer": settings.OPENAI_REFERER,
                "X-Title": settings.OPENAI_TITLE,
            },
            timeout=settings.OPENAI_TIMEOUT,
            max_retries=2,
        )

    async def audit(
        self,
        prompt: ListingAuditPrompt,
        *,
        request_id: uuid.UUID,
    ) -> ListingAuditProviderResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                temperature=0.2,
                max_tokens=MAX_OUTPUT_TOKENS["listing_audit"],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "listing_audit_llm_output",
                        "strict": True,
                        "schema": ListingAuditLLMOutput.model_json_schema(),
                    },
                },
                store=False,
            )
        except Exception as exc:
            raise AppException(
                message="AI generation failed",
                code=502,
                detail="The AI service is temporarily unavailable.",
                error_code=AI_PROVIDER_UNAVAILABLE,
                cause=exc,
            ) from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise ai_response_invalid_exception(exc) from exc
        if not content:
            raise ai_response_invalid_exception()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ai_response_invalid_exception(exc) from exc
        if not isinstance(payload, dict):
            raise ai_response_invalid_exception()

        try:
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
        except (AttributeError, TypeError) as exc:
            raise ai_response_invalid_exception(exc) from exc
        return ListingAuditProviderResponse(
            output=payload,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
