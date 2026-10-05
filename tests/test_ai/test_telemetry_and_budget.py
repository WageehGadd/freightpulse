import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.ai.budget_guard import (
    AIBudgetExceededError,
    AIRateLimitExceededError,
    BudgetGuard,
)
from app.ai.telemetry import AITelemetry
from app.config import settings
from app.main import app


class FakeRedis:
    """In-memory Redis simulator for budget and telemetry testing."""

    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.should_fail = False

    async def eval(self, script, numkeys, key, *args):
        if self.should_fail:
            raise ConnectionError("Simulated Redis failure")

        if "INCR" in script and "max_req" in script:
            # Rate limit script
            max_req = int(args[0])
            curr = self.store.get(key, 0) + 1
            self.store[key] = curr
            if max_req > 0 and curr > max_req:
                return 0
            return 1

        if "reserved_micro_usd" in script and "budget" in script and "HINCRBY" in script:
            # Budget reservation script
            est = int(args[0])
            budget = int(args[1])
            h = self.hashes.get(key, {})
            actual = int(h.get("actual_micro_usd", 0))
            reserved = int(h.get("reserved_micro_usd", 0))

            if budget > 0 and (actual + reserved + est) > budget:
                return 0

            h["reserved_micro_usd"] = reserved + est
            self.hashes[key] = h
            return 1

        if "HSET" in script and "actual_micro_usd" in script:
            # Reconciliation script
            est = int(args[0])
            actual = int(args[1])
            h = self.hashes.get(key, {})
            curr_reserved = int(h.get("reserved_micro_usd", 0))
            curr_actual = int(h.get("actual_micro_usd", 0))

            new_reserved = max(0, curr_reserved - est)
            h["reserved_micro_usd"] = new_reserved
            h["actual_micro_usd"] = curr_actual + actual
            self.hashes[key] = h
            return 1

        if "HSET" in script and "release" in script or "new_reserved" in script:
            # Release reservation script
            est = int(args[0])
            h = self.hashes.get(key, {})
            curr_reserved = int(h.get("reserved_micro_usd", 0))
            new_reserved = max(0, curr_reserved - est)
            h["reserved_micro_usd"] = new_reserved
            self.hashes[key] = h
            return 1

        return 1

    async def hincrby(self, key, field, amount):
        if self.should_fail:
            raise ConnectionError("Simulated Redis failure")
        h = self.hashes.get(key, {})
        curr = int(h.get(field, 0))
        h[field] = curr + amount
        self.hashes[key] = h

    async def expire(self, key, seconds):
        pass

    async def hgetall(self, key):
        if self.should_fail:
            raise ConnectionError("Simulated Redis failure")
        return self.hashes.get(key, {})

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:

    def __init__(self, fake_redis):
        self.fake_redis = fake_redis
        self.actions = []

    def hincrby(self, key, field, amount):
        self.actions.append(("hincrby", key, field, amount))

    def expire(self, key, seconds):
        self.actions.append(("expire", key, seconds))

    async def execute(self):
        for action in self.actions:
            if action[0] == "hincrby":
                await self.fake_redis.hincrby(action[1], action[2], action[3])


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.mark.asyncio
async def test_budget_guard_rate_limit(fake_redis):
    """Verify rate limit check blocks requests beyond configured limit."""
    with patch("app.ai.budget_guard.get_redis", return_value=fake_redis):
        with patch.object(settings, "AI_MAX_REQUESTS_PER_MINUTE", 2):
            # First 2 should succeed
            await BudgetGuard.check_and_reserve(0.001, "test_feature")
            await BudgetGuard.check_and_reserve(0.001, "test_feature")

            # 3rd should be rejected
            with pytest.raises(AIRateLimitExceededError):
                await BudgetGuard.check_and_reserve(0.001, "test_feature")


@pytest.mark.asyncio
async def test_budget_guard_daily_budget(fake_redis):
    """Verify daily budget limit blocks requests when budget is exceeded."""
    with patch("app.ai.budget_guard.get_redis", return_value=fake_redis):
        with patch.object(settings, "AI_DAILY_BUDGET_USD", 0.01):
            # First request for $0.008 -> allowed
            await BudgetGuard.check_and_reserve(0.008, "test_feature")

            # Second request for $0.005 ($0.008 + $0.005 > $0.01) -> blocked
            with pytest.raises(AIBudgetExceededError):
                await BudgetGuard.check_and_reserve(0.005, "test_feature")


@pytest.mark.asyncio
async def test_budget_reconciliation_and_refund(fake_redis):
    """Verify reconciliation updates actual spend and failure releases reservation."""
    with patch("app.ai.budget_guard.get_redis", return_value=fake_redis):
        with patch.object(settings, "AI_DAILY_BUDGET_USD", 10.0):
            # Reserve $0.005
            est_micro = await BudgetGuard.check_and_reserve(0.005, "test_feature")
            actual_usd, reserved_usd, committed_usd = await BudgetGuard.get_budget_status()

            assert reserved_usd == 0.005
            assert actual_usd == 0.0
            assert committed_usd == 0.005

            # Reconcile with actual cost $0.003
            await BudgetGuard.reconcile_success(est_micro, 0.003)
            actual_usd, reserved_usd, committed_usd = await BudgetGuard.get_budget_status()

            assert reserved_usd == 0.0
            assert actual_usd == 0.003
            assert committed_usd == 0.003

            # Reserve $0.004 then release on failure
            est_micro2 = await BudgetGuard.check_and_reserve(0.004, "test_feature")
            await BudgetGuard.release_reservation(est_micro2)
            actual_usd, reserved_usd, committed_usd = await BudgetGuard.get_budget_status()

            assert reserved_usd == 0.0
            assert actual_usd == 0.003
            assert committed_usd == 0.003


@pytest.mark.asyncio
async def test_concurrent_budget_reservations(fake_redis):
    """Verify atomic Lua execution handles concurrent budget reservation calls safely."""
    with patch("app.ai.budget_guard.get_redis", return_value=fake_redis):
        with patch.object(settings, "AI_DAILY_BUDGET_USD", 0.015):
            # Launch 5 concurrent tasks each requesting $0.005 (total $0.025 > $0.015)
            async def reserve_task():
                try:
                    await BudgetGuard.check_and_reserve(0.005, "test")
                    return True
                except AIBudgetExceededError:
                    return False

            results = await asyncio.gather(*[reserve_task() for _ in range(5)])

            # Exactly 3 should succeed ($0.015 / $0.005 = 3) and 2 should fail
            assert results.count(True) == 3
            assert results.count(False) == 2


@pytest.mark.asyncio
async def test_redis_fail_open_behavior(fake_redis):
    """Verify fail-open policy allows execution when Redis is unreachable."""
    fake_redis.should_fail = True
    with patch("app.ai.budget_guard.get_redis", return_value=fake_redis):
        with patch("app.ai.telemetry.get_redis", return_value=fake_redis):
            with patch.object(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True):
                with patch.object(settings, "AI_DAILY_BUDGET_USD", 10.0):
                    # BudgetGuard check should log warning and return cleanly
                    est_micro = await BudgetGuard.check_and_reserve(0.005, "test_feature")
                    assert est_micro == 5000

                    # Telemetry write should fail open without raising exception
                    await AITelemetry.record_call("carrier_summarizer", "v1", "gpt-4o-mini", True, 0.2)


def test_ai_admin_endpoints_require_authentication():
    """Verify /api/v1/ai/* endpoints require valid JWT authentication."""
    client = TestClient(app)

    response_health = client.get("/api/v1/ai/health")
    assert response_health.status_code == 401

    response_metrics = client.get("/api/v1/ai/metrics")
    assert response_metrics.status_code == 401

    response_prompts = client.get("/api/v1/ai/prompts")
    assert response_prompts.status_code == 401


def test_ai_prompts_endpoint_hides_raw_prompt_templates():
    """Verify /api/v1/ai/prompts returns metadata but NEVER raw system/user prompt templates."""
    client = TestClient(app)
    from app.auth.security import get_current_user
    from app.auth.rate_limit import RateLimiter
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[RateLimiter] = lambda: None

    try:
        res = client.get("/api/v1/ai/prompts")
        assert res.status_code == 200

        data = res.json()
        assert "features" in data
        features = data["features"]

        assert "carrier_summarizer" in features
        assert "rate_outlook" in features
        assert "route_brief" in features

        # Verify safe metadata is returned
        c_info = features["carrier_summarizer"]
        assert c_info["active_version"] == "v1"
        assert "v1" in c_info["available_versions"]

        # Ensure NO system_prompt or user_template text is present in the response
        raw_text = res.text
        assert "SYSTEM_PROMPT" not in raw_text
        assert "CRITICAL RULES" not in raw_text
        assert "Advisory Text:" not in raw_text

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,responses,success", [
    ("success",1,True),("refusal",1,False),("refusal_no_usage",0,False),
    ("validation_retry",2,True),("validation_exhaustion",3,False),("post_response_failure",1,False),
])
async def test_client_accounting_preserves_other_reservation(fake_redis,scenario,responses,success):
    from types import SimpleNamespace
    from pydantic import ValidationError
    from app.ai.openai_client import FreightPulseAIClient,AIValidationError
    from app.schemas.ai_outputs import GroundedRateOutlookOutput
    narrative=GroundedRateOutlookOutput(outlook_text="Synthetic explanatory narrative meeting the required length boundary.")
    count=0
    def response():
        nonlocal count
        count+=1
        invalid=scenario=="validation_exhaustion" or (scenario=="validation_retry" and count==1)
        refused=scenario.startswith("refusal")
        def parse():
            if invalid:
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None,parsed={"outlook_text":"short"}))])
            if scenario=="post_response_failure":raise RuntimeError("Synthetic parser failure")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal="Synthetic refusal" if refused else None,parsed=None if refused else narrative))])
        raw=SimpleNamespace(json=lambda:{"usage":None if scenario=="refusal_no_usage" else
            {"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}},parse=parse)
        raw.http_response=raw
        return raw
    client=object.__new__(FreightPulseAIClient)
    provider=AsyncMock(side_effect=lambda **kwargs:response())
    client.client=SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        with_raw_response=SimpleNamespace(parse=provider)))))
    client.model="synthetic";client.temperature=1.0;client.max_tokens=100
    client.cost_per_1m_input_tokens=1.0;client.cost_per_1m_output_tokens=2.0
    with patch("app.ai.budget_guard.get_redis",return_value=fake_redis),patch("app.ai.telemetry.get_redis",return_value=fake_redis), \
         patch.object(settings,"AI_DAILY_BUDGET_USD",1.0),patch.object(settings,"AI_MAX_REQUESTS_PER_MINUTE",0), \
         patch.object(BudgetGuard,"estimate_request_cost",return_value=0.0001),patch("app.ai.openai_client.asyncio.sleep",new_callable=AsyncMock):
        # A's independent reservation must survive B's outcome/cleanup.
        await BudgetGuard.check_and_reserve(0.0002,"request_a")
        with patch.object(BudgetGuard,"check_and_reserve",wraps=BudgetGuard.check_and_reserve) as reserve, \
             patch.object(BudgetGuard,"reconcile_success",wraps=BudgetGuard.reconcile_success) as reconcile, \
             patch.object(BudgetGuard,"release_reservation",wraps=BudgetGuard.release_reservation) as release:
            call=client.generate_structured("Synthetic","Synthetic",GroundedRateOutlookOutput,"accounting_b")
            if success:
                assert await call==narrative
            else:
                error=RuntimeError if scenario=="post_response_failure" else AIValidationError
                with pytest.raises(error):await call
            reserve.assert_awaited_once();reconcile.assert_awaited_once();release.assert_not_awaited()
        actual,reserved,committed=await BudgetGuard.get_budget_status()
        assert reserved==0.0002
        assert actual==pytest.approx(responses*0.000020)
        assert committed==pytest.approx(reserved+actual)
    metrics=[value for key,value in fake_redis.hashes.items() if key.startswith("ai:metrics:daily:")]
    assert len(metrics)==1
    m=metrics[0]
    assert m["requests"]==1
    assert m.get("successes",0)==int(success) and m.get("errors",0)==int(not success)
    assert m["requests"]==m.get("successes",0)+m.get("errors",0)
    assert m["input_tokens"]==10*responses and m["output_tokens"]==5*responses
    assert m["cost_micro_usd"]==20*responses
    assert provider.await_count==(2 if scenario=="validation_retry" else 3 if scenario=="validation_exhaustion" else 1)


@pytest.mark.asyncio
async def test_client_telemetry_outage_does_not_repeat_financial_settlement(fake_redis):
    from types import SimpleNamespace
    from app.ai.openai_client import FreightPulseAIClient
    from app.schemas.ai_outputs import GroundedRateOutlookOutput
    output=GroundedRateOutlookOutput(outlook_text="Synthetic explanatory narrative meeting the required length boundary.")
    raw=SimpleNamespace(json=lambda:{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}},
        parse=lambda:SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None,parsed=output))]))
    raw.http_response=raw
    provider=AsyncMock(return_value=raw)
    client=object.__new__(FreightPulseAIClient)
    client.client=SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(parse=provider)))))
    client.model="synthetic";client.temperature=1.0;client.max_tokens=100
    client.cost_per_1m_input_tokens=client.cost_per_1m_output_tokens=0.0
    fake_redis.should_fail=True
    with patch.object(BudgetGuard,"check_and_reserve",AsyncMock(return_value=100)), \
         patch.object(BudgetGuard,"reconcile_success",new_callable=AsyncMock) as reconcile, \
         patch.object(BudgetGuard,"release_reservation",new_callable=AsyncMock) as release, \
         patch("app.ai.telemetry.get_redis",return_value=fake_redis):
        assert await client.generate_structured("Synthetic","Synthetic",GroundedRateOutlookOutput,"outage")==output
    provider.assert_awaited_once();reconcile.assert_awaited_once_with(100,0.0);release.assert_not_awaited()
