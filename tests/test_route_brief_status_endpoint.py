# pyrefly: ignore [missing-import]
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from fastapi import status, HTTPException

from app.schemas.route_brief import RouteBriefStatusResponse
from app.models.route_brief import RouteBrief
from app.models.user import User
from app.routers.route_brief import get_route_brief_status


class DummyModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_route_brief_status_response_schema_pending():
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    resp = RouteBriefStatusResponse(
        brief_id=brief_id,
        status="pending",
        brief_markdown=None,
        recommendation=None,
        risk_level=None,
        error_message=None,
        created_at=now,
    )
    dumped = resp.model_dump()
    assert dumped["brief_id"] == brief_id
    assert dumped["id"] == brief_id
    assert dumped["status"] == "pending"
    assert dumped["brief_markdown"] is None
    assert dumped["recommendation"] is None
    assert dumped["risk_level"] is None
    assert dumped["error_message"] is None
    assert dumped["created_at"] == now


def test_route_brief_status_response_schema_generating():
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    resp = RouteBriefStatusResponse(
        id=brief_id,
        status="generating",
        created_at=now,
    )
    dumped = resp.model_dump()
    assert dumped["brief_id"] == brief_id
    assert dumped["id"] == brief_id
    assert dumped["status"] == "generating"
    assert dumped["brief_markdown"] is None
    assert dumped["recommendation"] is None
    assert dumped["risk_level"] is None


def test_route_brief_status_response_schema_completed():
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    resp = RouteBriefStatusResponse(
        brief_id=brief_id,
        status="completed",
        brief_markdown="# Detailed Route Brief Report",
        recommendation="ship_now",
        risk_level="low",
        error_message=None,
        created_at=now,
    )
    dumped = resp.model_dump()
    assert dumped["brief_id"] == brief_id
    assert dumped["id"] == brief_id
    assert dumped["status"] == "completed"
    assert dumped["brief_markdown"] == "# Detailed Route Brief Report"
    assert dumped["recommendation"] == "ship_now"
    assert dumped["risk_level"] == "low"
    assert dumped["error_message"] is None
    assert dumped["created_at"] == now


def test_route_brief_status_response_schema_from_orm():
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    dummy_brief = DummyModel(
        id=brief_id,
        status="completed",
        brief_markdown="# Analysis",
        recommendation="monitor_closely",
        risk_level="medium",
        error_message=None,
        created_at=now,
    )
    resp = RouteBriefStatusResponse.model_validate(dummy_brief)
    assert resp.brief_id == brief_id
    assert resp.id == brief_id
    assert resp.status == "completed"
    assert resp.brief_markdown == "# Analysis"
    assert resp.recommendation == "monitor_closely"
    assert resp.risk_level == "medium"
    assert resp.created_at == now


@pytest.mark.asyncio
async def test_get_route_brief_status_handler_pending():
    user_id = uuid.uuid4()
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    current_user = User(id=user_id, email="user@test.com", is_admin=False)

    mock_brief = DummyModel(
        id=brief_id,
        user_id=user_id,
        status="pending",
        brief_markdown=None,
        recommendation=None,
        risk_level=None,
        error_message=None,
        created_at=now,
    )

    mock_db = AsyncMock()
    mock_db.get.return_value = mock_brief

    res = await get_route_brief_status(
        brief_id=brief_id,
        current_user=current_user,
        db=mock_db,
    )

    assert res.brief_id == brief_id
    assert res.id == brief_id
    assert res.status == "pending"
    assert res.brief_markdown is None
    assert res.recommendation is None
    assert res.risk_level is None
    assert res.error_message is None
    assert res.created_at == now


@pytest.mark.asyncio
async def test_get_route_brief_status_handler_completed():
    user_id = uuid.uuid4()
    brief_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    current_user = User(id=user_id, email="user@test.com", is_admin=False)

    mock_brief = DummyModel(
        id=brief_id,
        user_id=user_id,
        status="completed",
        brief_markdown="# Finished Report",
        recommendation="ship_now",
        risk_level="low",
        error_message=None,
        created_at=now,
    )

    mock_db = AsyncMock()
    mock_db.get.return_value = mock_brief

    res = await get_route_brief_status(
        brief_id=brief_id,
        current_user=current_user,
        db=mock_db,
    )

    assert res.brief_id == brief_id
    assert res.id == brief_id
    assert res.status == "completed"
    assert res.brief_markdown == "# Finished Report"
    assert res.recommendation == "ship_now"
    assert res.risk_level == "low"
    assert res.error_message is None
    assert res.created_at == now


@pytest.mark.asyncio
async def test_get_route_brief_status_handler_not_found():
    user_id = uuid.uuid4()
    brief_id = uuid.uuid4()
    current_user = User(id=user_id, email="user@test.com", is_admin=False)

    mock_db = AsyncMock()
    mock_db.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_route_brief_status(
            brief_id=brief_id,
            current_user=current_user,
            db=mock_db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Route brief not found"


@pytest.mark.asyncio
async def test_get_route_brief_status_handler_unauthorized_other_tenant():
    user_id_a = uuid.uuid4()
    user_id_b = uuid.uuid4()
    brief_id = uuid.uuid4()
    current_user = User(id=user_id_b, email="b@test.com", is_admin=False)

    mock_brief = DummyModel(
        id=brief_id,
        user_id=user_id_a,
        status="completed",
        brief_markdown="Secret",
        recommendation="ship_now",
        risk_level="low",
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )

    mock_db = AsyncMock()
    mock_db.get.return_value = mock_brief

    with pytest.raises(HTTPException) as exc_info:
        await get_route_brief_status(
            brief_id=brief_id,
            current_user=current_user,
            db=mock_db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Route brief not found"
