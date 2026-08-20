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
