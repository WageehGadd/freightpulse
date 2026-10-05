import json
from unittest.mock import AsyncMock, MagicMock, patch

import openai
from pydantic import ValidationError
import pytest

from app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from app.schemas.ai_outputs import RateOutlookOutput


@pytest.fixture
def mock_openai():
    with patch("app.ai.openai_client.AsyncAzureOpenAI") as mock:
        yield mock

@pytest.fixture
def ai_client(mock_openai):
    # Client tests must never reach runtime Redis accounting.
    with patch("app.ai.openai_client.BudgetGuard.check_and_reserve", new_callable=AsyncMock, return_value=100), \
         patch("app.ai.openai_client.BudgetGuard.reconcile_success", new_callable=AsyncMock), \
         patch("app.ai.openai_client.BudgetGuard.release_reservation", new_callable=AsyncMock), \
         patch("app.ai.openai_client.AITelemetry.record_call", new_callable=AsyncMock):
        yield FreightPulseAIClient(api_key="test-key")

@pytest.mark.asyncio
async def test_generate_structured_success(ai_client):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="wait",
            confidence=85
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_response.http_response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    mock_response.parse.return_value = mock_response
    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(return_value=mock_response)

    # Call method
    result = await ai_client.generate_structured(
        system_prompt="You are a helpful assistant.",
        user_content="What is the outlook?",
        output_schema=RateOutlookOutput,
        feature_name="test_feature"
    )

    # Assertions
    assert isinstance(result, RateOutlookOutput)
    assert result.recommendation == "wait"
    assert result.confidence == 85
    ai_client.client.beta.chat.completions.with_raw_response.parse.assert_called_once()


@pytest.mark.asyncio
async def test_generate_structured_retry_on_timeout(ai_client):
    # Setup mock to raise timeout then succeed
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=90
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_response.http_response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    mock_response.parse.return_value = mock_response

    # Needs to fail once, then succeed
    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(side_effect=[
        openai.APITimeoutError(request=MagicMock()),
        mock_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.with_raw_response.parse.call_count == 2
        mock_sleep.assert_called_once()

@pytest.mark.asyncio
async def test_generate_structured_validation_error_retry(ai_client):
    mock_valid_response = MagicMock()
    mock_valid_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=95
        )))
    ]
    mock_valid_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_valid_response.http_response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    mock_valid_response.parse.return_value = mock_valid_response

    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(side_effect=[
        ValidationError.from_exception_data(title="RateOutlookOutput", line_errors=[]),
        mock_valid_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.with_raw_response.parse.call_count == 2
        # Verify prompt got adjusted
        call_args = ai_client.client.beta.chat.completions.with_raw_response.parse.call_args_list[1]
        messages = call_args[1]["messages"]
        assert "Previous response failed validation" in messages[1]["content"]

@pytest.mark.asyncio
async def test_generate_structured_max_retries_exceeded(ai_client):
    # Always raise timeout
    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(side_effect=openai.APITimeoutError(request=MagicMock()))

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(AITimeoutError):
            await ai_client.generate_structured(
                system_prompt="System",
                user_content="User",
                output_schema=RateOutlookOutput,
                feature_name="test_feature"
            )

        assert ai_client.client.beta.chat.completions.with_raw_response.parse.call_count == 3 # Initial + 2 retries


@pytest.mark.asyncio
async def test_generate_structured_json_decode_error_retry(ai_client):
    mock_valid_response = MagicMock()
    mock_valid_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=95
        )))
    ]
    mock_valid_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_valid_response.http_response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    mock_valid_response.parse.return_value = mock_valid_response

    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(side_effect=[
        json.JSONDecodeError("Expecting value", "", 0),
        mock_valid_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.with_raw_response.parse.call_count == 2


def test_normalize_azure_endpoint():
    from app.ai.openai_client import normalize_azure_endpoint

    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/v1") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/v1/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("") == ""
    assert normalize_azure_endpoint(None) == ""


@pytest.mark.asyncio
async def test_generate_structured_passes_max_completion_tokens(ai_client):
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="wait",
            confidence=85
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_response.http_response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    mock_response.parse.return_value = mock_response
    ai_client.client.beta.chat.completions.with_raw_response.parse = AsyncMock(return_value=mock_response)

    await ai_client.generate_structured(
        system_prompt="System",
        user_content="User",
        output_schema=RateOutlookOutput,
        feature_name="test_feature",
        max_tokens=1500,
        temperature=1.0,
    )

    ai_client.client.beta.chat.completions.with_raw_response.parse.assert_called_once()
    call_kwargs = ai_client.client.beta.chat.completions.with_raw_response.parse.call_args.kwargs
    assert "max_completion_tokens" in call_kwargs
    assert call_kwargs["max_completion_tokens"] == 1500
    assert "max_tokens" not in call_kwargs


# Real SDK structured parser over local HTTP transport; no provider/network/Redis.
@pytest.mark.asyncio
@pytest.mark.parametrize("events,exception,attempts,responses,successful", [
    (["success"], None, 1, 1, True),
    (["success_zero_price"], None, 1, 1, True),
    (["refusal"], AIValidationError, 1, 1, False),
    (["refusal_no_usage"], AIValidationError, 1, 0, False),
    (["invalid", "success"], None, 2, 2, True),
    (["invalid", "invalid", "invalid"], AIValidationError, 3, 3, False),
    (["timeout", "success"], None, 2, 1, True),
    (["connection", "success"], None, 2, 1, True),
    (["rate", "success"], None, 2, 1, True),
    (["server", "success"], None, 2, 1, True),
    (["terminal"], openai.BadRequestError, 1, 0, False),
    (["timeout", "timeout", "timeout"], AITimeoutError, 3, 0, False),
    (["invalid", "timeout", "timeout"], AITimeoutError, 3, 1, False),
    (["empty", "empty", "empty"], AIValidationError, 3, 3, False),
])
async def test_sdk_logical_accounting_matrix(events, exception, attempts, responses, successful):
    import httpx
    from app.ai.openai_client import BudgetGuard, AITelemetry
    from app.schemas.ai_outputs import GroundedRateOutlookOutput
    requests = []
    narrative = "Synthetic explanatory output long enough for the grounded narrative schema."
    def transport(request):
        event = events[len(requests)]
        requests.append(request)
        if event == "timeout":
            raise httpx.ReadTimeout("Synthetic timeout", request=request)
        if event == "connection":
            raise httpx.ConnectError("Synthetic connection failure", request=request)
        if event in ("terminal", "rate", "server"):
            return httpx.Response({"terminal":400,"rate":429,"server":500}[event],
                json={"error":{"message":"Synthetic failure","type":"test"}},request=request)
        refused = event.startswith("refusal")
        body = {"id":"synthetic", "object":"chat.completion", "created":0,"model":"synthetic",
            "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant",
                "content":None if refused or event=="empty" else json.dumps({"outlook_text":"too short" if event=="invalid" else narrative}),
                "refusal":"Synthetic refusal" if refused else None}}],
            "usage":None if event=="refusal_no_usage" else {"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}
        return httpx.Response(200,json=body,request=request)
    sdk = openai.AsyncAzureOpenAI(api_key="synthetic-test-credential",azure_endpoint="https://example.test",
        api_version="2024-02-15-preview",max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    client = object.__new__(FreightPulseAIClient)
    client.client=sdk; client.model="gpt-5-mini"; client.temperature=1.0; client.max_tokens=100
    zero_price=events==["success_zero_price"]
    client.cost_per_1m_input_tokens=0.0 if zero_price else 1.0
    client.cost_per_1m_output_tokens=0.0 if zero_price else 2.0
    expected_cost=0.0 if zero_price else 0.000020*responses
    reserve=AsyncMock(return_value=100); reconcile=AsyncMock(); release=AsyncMock(); telemetry=AsyncMock()
    try:
        with patch.object(BudgetGuard,"check_and_reserve",reserve),patch.object(BudgetGuard,"reconcile_success",reconcile), \
             patch.object(BudgetGuard,"release_reservation",release),patch.object(AITelemetry,"record_call",telemetry), \
             patch("app.ai.openai_client.asyncio.sleep",new_callable=AsyncMock):
            call=client.generate_structured("Synthetic system","Synthetic user",GroundedRateOutlookOutput,"matrix")
            if exception:
                with pytest.raises(exception): await call
            else:
                result=await call
                assert result==GroundedRateOutlookOutput(outlook_text=narrative)
        assert len(requests)==attempts
        reserve.assert_awaited_once()
        telemetry.assert_awaited_once()
        record=telemetry.await_args.kwargs
        assert record["success"] is successful
        assert record["input_tokens"]==10*responses and record["output_tokens"]==5*responses
        assert record["actual_cost"]==pytest.approx(expected_cost)
        if responses or events==["refusal_no_usage"]:
            reconcile.assert_awaited_once_with(100,pytest.approx(expected_cost))
            release.assert_not_awaited()
        else:
            release.assert_awaited_once_with(100)
            reconcile.assert_not_awaited()
        if "invalid" in events and len(events)>1:
            assert "Previous response failed validation" in json.loads(requests[1].content)["messages"][1]["content"]
    finally:
        await sdk.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_applied",[False,True])
async def test_reconciliation_failure_never_releases_or_retries(ai_client, remote_applied):
    from types import SimpleNamespace
    from app.ai.openai_client import BudgetGuard,AITelemetry
    output=RateOutlookOutput(outlook_text="Synthetic valid output exceeding the required minimum length.",recommendation="wait",confidence=1)
    response=SimpleNamespace(json=lambda:{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}},
        parse=lambda:SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None,parsed=output))]))
    response.http_response=response
    provider=AsyncMock(return_value=response)
    ai_client.client.beta.chat.completions.with_raw_response.parse=provider
    state={"reserved":300,"actual":0}
    async def uncertain(estimate,actual):
        if remote_applied:
            state["reserved"]-=estimate;state["actual"]+=actual
        raise ConnectionError("Synthetic indeterminate acknowledgement")
    reconcile=AsyncMock(side_effect=uncertain);release=AsyncMock();telemetry=AsyncMock()
    with patch.object(BudgetGuard,"reconcile_success",reconcile),patch.object(BudgetGuard,"release_reservation",release),patch.object(AITelemetry,"record_call",telemetry):
        with pytest.raises(ConnectionError):
            await ai_client.generate_structured("Synthetic","Synthetic",RateOutlookOutput,"uncertain")
    provider.assert_awaited_once();reconcile.assert_awaited_once();release.assert_not_awaited()
    telemetry.assert_awaited_once()
    assert telemetry.await_args.kwargs["success"] is False
    assert telemetry.await_args.kwargs["input_tokens"]==10
    assert state["reserved"]==(200 if remote_applied else 300)


@pytest.mark.asyncio
async def test_budget_rejection_has_one_outcome_no_provider_or_cleanup(ai_client):
    from app.ai.openai_client import BudgetGuard,AITelemetry
    from app.ai.budget_guard import AIBudgetExceededError
    provider=AsyncMock();ai_client.client.beta.chat.completions.with_raw_response.parse=provider
    reconcile=AsyncMock();release=AsyncMock();telemetry=AsyncMock()
    with patch.object(BudgetGuard,"check_and_reserve",AsyncMock(side_effect=AIBudgetExceededError("Synthetic denial"))), \
         patch.object(BudgetGuard,"reconcile_success",reconcile),patch.object(BudgetGuard,"release_reservation",release),patch.object(AITelemetry,"record_call",telemetry):
        with pytest.raises(AIBudgetExceededError):
            await ai_client.generate_structured("Synthetic","Synthetic",RateOutlookOutput,"denied")
    provider.assert_not_awaited();reconcile.assert_not_awaited();release.assert_not_awaited()
    telemetry.assert_awaited_once()
    assert telemetry.await_args.kwargs["success"] is False
    assert telemetry.await_args.kwargs.get("input_tokens",0)==0


@pytest.mark.asyncio
async def test_cancellation_retains_existing_unsupported_cleanup_boundary(ai_client):
    import asyncio
    from app.ai.openai_client import BudgetGuard,AITelemetry
    ai_client.client.beta.chat.completions.with_raw_response.parse=AsyncMock(side_effect=asyncio.CancelledError())
    reconcile=AsyncMock();release=AsyncMock();telemetry=AsyncMock()
    with patch.object(BudgetGuard,"reconcile_success",reconcile),patch.object(BudgetGuard,"release_reservation",release),patch.object(AITelemetry,"record_call",telemetry):
        with pytest.raises(asyncio.CancelledError):
            await ai_client.generate_structured("Synthetic","Synthetic",RateOutlookOutput,"cancelled")
    reconcile.assert_not_awaited();release.assert_not_awaited();telemetry.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_post_settlement_telemetry_exception_has_no_cleanup(ai_client):
    from types import SimpleNamespace
    from app.ai.openai_client import BudgetGuard,AITelemetry
    output=RateOutlookOutput(outlook_text="Synthetic valid output exceeding the required minimum length.",recommendation="wait",confidence=1)
    raw=SimpleNamespace(http_response=SimpleNamespace(json=lambda:{"usage":None}),
        parse=lambda:SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None,parsed=output))]))
    provider=AsyncMock(return_value=raw)
    ai_client.client.beta.chat.completions.with_raw_response.parse=provider
    reconcile=AsyncMock();release=AsyncMock();telemetry=AsyncMock(side_effect=RuntimeError("Synthetic telemetry bug"))
    with patch.object(BudgetGuard,"reconcile_success",reconcile),patch.object(BudgetGuard,"release_reservation",release),patch.object(AITelemetry,"record_call",telemetry):
        with pytest.raises(RuntimeError):
            await ai_client.generate_structured("Synthetic","Synthetic",RateOutlookOutput,"post_settlement")
    provider.assert_awaited_once();reconcile.assert_awaited_once();release.assert_not_awaited();telemetry.assert_awaited_once()
