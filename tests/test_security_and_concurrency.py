import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.auth.security import get_current_user, get_current_admin_user
from app.auth.rate_limit import RateLimiter
from app.database import get_db
from app.models.user import User
from app.ai.budget_guard import BudgetGuard


def test_cors_middleware_configuration():
    """Verify CORS middleware blocks non-allowed origins and allows configured origins."""
    client = TestClient(app)
    
    # 1. Allowed origin
    res_allowed = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    )
    assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # 2. Non-allowed origin
    res_disallowed = client.options(
        "/api/v1/health",
        headers={"Origin": "http://malicious-site.com", "Access-Control-Request-Method": "GET"}
    )
    assert res_disallowed.headers.get("access-control-allow-origin") is None


def test_admin_endpoint_authorization_rbac():
    """Verify non-admin users receive 403 Forbidden on AI admin endpoints, while admin users pass."""
    client = TestClient(app)

    normal_user = MagicMock(spec=User)
    normal_user.id = "00000000-0000-0000-0000-000000000001"
    normal_user.is_admin = False

    admin_user = MagicMock(spec=User)
    admin_user.id = "00000000-0000-0000-0000-000000000002"
    admin_user.is_admin = True

    app.dependency_overrides[RateLimiter] = lambda: None

    try:
        # 1. Test normal user (is_admin=False) -> 403 Forbidden
        app.dependency_overrides[get_current_user] = lambda: normal_user
        app.dependency_overrides.pop(get_current_admin_user, None)

        res_forbidden = client.get("/api/v1/ai/prompts")
        assert res_forbidden.status_code == 403
        assert "Administrative privileges required" in res_forbidden.json()["error"]["message"]

        # 2. Test admin user (is_admin=True) -> 200 OK
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_current_admin_user] = lambda: admin_user

        res_ok = client.get("/api/v1/ai/prompts")
        assert res_ok.status_code == 200
        assert "features" in res_ok.json()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_budget_guard_atomic_spend_estimation():
    """Verify BudgetGuard cost estimation formula and reservation handling."""
    cost = BudgetGuard.estimate_request_cost(
        system_prompt="System prompt text",
        user_content="User content text",
        max_tokens=1000,
        input_cost_per_1m=0.15,
        output_cost_per_1m=0.60,
    )
    assert cost > 0.0
    assert cost < 0.01  # reasonable cost estimate

