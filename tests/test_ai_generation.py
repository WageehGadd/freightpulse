import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks import ai_generation
from app.ai.adapter import AdvisoryNotFoundError
from app.ai.adapter import AdvisoryEmptyError
from app.ai.openai_client import AITimeoutError
from app.schemas.ai_outputs import CarrierSummaryOutput


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_summarize_advisory_persists_ai_output_without_overwriting_source_type():
    advisory_id = uuid.uuid4()
    advisory = MagicMock(
        id=advisory_id,
        carrier="MSC",
        title="Route update",
        raw_text="Source advisory text",
        advisory_type="schedule_change",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=advisory)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(
        return_value=CarrierSummaryOutput(
            summary="A sufficiently detailed source-grounded advisory summary.",
            affected_lanes=["Egypt-Europe"],
            impact_severity="high",
        )
    )

    result = await ai_generation.summarize_advisory_async(
        str(advisory_id),
        session_factory=lambda: FakeSessionContext(session),
        summarizer_factory=lambda: summarizer,
    )

    session.get.assert_awaited_once_with(ai_generation.CarrierAdvisory, advisory_id)
    summarizer.summarize.assert_awaited_once_with(
        carrier="MSC",
        title="Route update",
        advisory_text="Source advisory text",
    )
    session.commit.assert_awaited_once()
    assert advisory.summary == "A sufficiently detailed source-grounded advisory summary."
    assert advisory.impact_severity == "high"
    assert advisory.affected_lanes == ["Egypt-Europe"]
    assert advisory.advisory_type == "schedule_change"
    assert result == {
        "advisory_id": str(advisory_id),
        "summary_length": len(advisory.summary),
        "impact_severity": "high",
    }


@pytest.mark.asyncio
async def test_summarize_advisory_rejects_invalid_uuid():
    with pytest.raises(ai_generation.InvalidAdvisoryIdError, match="Invalid advisory UUID"):
        await ai_generation.summarize_advisory_async("not-a-uuid")


@pytest.mark.asyncio
async def test_summarize_advisory_reports_missing_advisory():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    with pytest.raises(AdvisoryNotFoundError, match="not found"):
        await ai_generation.summarize_advisory_async(
            str(uuid.uuid4()),
            session_factory=lambda: FakeSessionContext(session),
            summarizer_factory=MagicMock(),
        )


@pytest.mark.asyncio
async def test_summarize_advisory_rejects_empty_source_without_calling_ai():
    advisory = MagicMock(
        id=uuid.uuid4(),
        raw_text="   ",
        advisory_type="schedule_change",
        source_url="https://carrier.example/advisory",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=advisory)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock()

    with pytest.raises(AdvisoryEmptyError, match="empty raw text"):
        await ai_generation.summarize_advisory_async(
            str(advisory.id),
            session_factory=lambda: FakeSessionContext(session),
            summarizer_factory=lambda: summarizer,
        )

    summarizer.summarize.assert_not_awaited()
    session.commit.assert_not_awaited()
    assert advisory.raw_text == "   "
    assert advisory.advisory_type == "schedule_change"
    assert advisory.source_url == "https://carrier.example/advisory"


@pytest.mark.asyncio
async def test_summarize_advisory_rolls_back_ai_failure_without_changing_source_fields():
    advisory = MagicMock(
        id=uuid.uuid4(),
        carrier="MSC",
        title="Source title",
        raw_text="Source text",
        advisory_type="schedule_change",
        source_url="https://carrier.example/advisory",
        published_at="2026-08-15",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=advisory)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(side_effect=AITimeoutError("timeout"))

    with pytest.raises(AITimeoutError):
        await ai_generation.summarize_advisory_async(
            str(advisory.id),
            session_factory=lambda: FakeSessionContext(session),
            summarizer_factory=lambda: summarizer,
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert advisory.raw_text == "Source text"
    assert advisory.advisory_type == "schedule_change"
    assert advisory.source_url == "https://carrier.example/advisory"
    assert advisory.published_at == "2026-08-15"


@pytest.mark.asyncio
async def test_repeated_summarization_regenerates_ai_fields_without_corrupting_source_fields():
    advisory_id = uuid.uuid4()
    advisory = MagicMock(
        id=advisory_id,
        carrier="MSC",
        title="Source title",
        raw_text="Original source text",
        advisory_type="schedule_change",
        source_url="https://carrier.example/advisory",
        published_at="2026-08-15",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=advisory)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(
        side_effect=[
            CarrierSummaryOutput(
                summary="First sufficiently detailed generated advisory summary.",
                affected_lanes=["Egypt-Europe"],
                impact_severity="medium",
            ),
            CarrierSummaryOutput(
                summary="Second sufficiently detailed generated advisory summary.",
                affected_lanes=["Egypt-Europe", "UAE-Europe"],
                impact_severity="high",
            ),
        ]
    )

    for _ in range(2):
        await ai_generation.summarize_advisory_async(
            str(advisory_id),
            session_factory=lambda: FakeSessionContext(session),
            summarizer_factory=lambda: summarizer,
        )

    assert advisory.summary == "Second sufficiently detailed generated advisory summary."
    assert advisory.impact_severity == "high"
    assert advisory.affected_lanes == ["Egypt-Europe", "UAE-Europe"]
    assert advisory.raw_text == "Original source text"
    assert advisory.advisory_type == "schedule_change"
    assert advisory.source_url == "https://carrier.example/advisory"
    assert advisory.published_at == "2026-08-15"
    assert session.commit.await_count == 2


def test_celery_task_accepts_uuid_string(monkeypatch):
    advisory_id = str(uuid.uuid4())
    expected = {"advisory_id": advisory_id, "summary_length": 42, "impact_severity": "low"}
    monkeypatch.setattr(ai_generation, "summarize_advisory_async", AsyncMock(return_value=expected))

    assert ai_generation.summarize_advisory.run(advisory_id) == expected


def test_celery_task_rejects_invalid_uuid():
    with pytest.raises(ai_generation.InvalidAdvisoryIdError, match="Invalid advisory UUID"):
        ai_generation.summarize_advisory.run("not-a-uuid")


def test_ai_services_do_not_import_sqlalchemy():
    ai_root = Path("app/ai")
    for service in ai_root.rglob("*.py"):
        assert "sqlalchemy" not in service.read_text().lower()
