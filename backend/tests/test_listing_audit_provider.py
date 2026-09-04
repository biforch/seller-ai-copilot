from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.analysis.prompt import ListingAuditPrompt
from app.analysis.provider import OpenAIListingAuditProvider
from app.analysis.schemas import ListingAuditLLMOutput
from app.core.exceptions import AI_RESPONSE_INVALID, AppException

from .test_listing_audit_baseline import valid_output


@pytest.mark.asyncio
async def test_provider_uses_json_mode_no_store_and_accounting_metadata() -> None:
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(valid_output())))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34),
        )

    provider = OpenAIListingAuditProvider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = await provider.audit(
        ListingAuditPrompt(system="system", user="untrusted listing"),
        request_id=uuid.uuid4(),
    )

    assert captured["store"] is False
    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"] == {
        "name": "listing_audit_llm_output",
        "strict": True,
        "schema": ListingAuditLLMOutput.model_json_schema(),
    }
    assert captured["temperature"] == 0.2
    assert captured["messages"][1]["content"] == "untrusted listing"
    assert result.input_tokens == 12
    assert result.output_tokens == 34


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [SimpleNamespace(choices=[]), SimpleNamespace(choices=None)])
async def test_provider_rejects_malformed_choice_shape(response) -> None:
    async def create(**kwargs):
        return response

    provider = OpenAIListingAuditProvider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(AppException) as caught:
        await provider.audit(
            ListingAuditPrompt(system="system", user="data"), request_id=uuid.uuid4()
        )
    assert caught.value.error_code == AI_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_provider_rejects_malformed_usage_shape() -> None:
    async def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(valid_output())))],
            usage=SimpleNamespace(prompt_tokens="not-an-integer"),
        )

    provider = OpenAIListingAuditProvider()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(AppException) as caught:
        await provider.audit(
            ListingAuditPrompt(system="system", user="data"), request_id=uuid.uuid4()
        )
    assert caught.value.error_code == AI_RESPONSE_INVALID
