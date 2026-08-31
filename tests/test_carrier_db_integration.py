import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.carrier_advisory import CarrierAdvisory
from app.tasks.ai_generation import (
    summarize_advisory_async,
    InvalidAdvisoryIdError,
)
from app.ai.adapter import AdvisoryNotFoundError, AdvisoryEmptyError
from app.ai.openai_client import AITimeoutError
from app.schemas.ai_outputs import CarrierSummaryOutput

class FakeSessionContext:
    def __init__(self, session):
        self.session = session
    async def __aenter__(self):
        return self.session
    async def __aexit__(self, exc_type, exc, traceback):
        return False

@pytest.fixture
def mock_summarizer():
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(
        return_value=CarrierSummaryOutput(
            summary="A real db-integrated summary.",
            affected_lanes=["Asia-Europe"],
            impact_severity="high",
            effective_date=None,
        )
    )
    return summarizer

@pytest.mark.asyncio
async def test_real_db_success_persistence(db_session, mock_summarizer):
    advisory = CarrierAdvisory(
        carrier="Maersk",
        advisory_type="surcharge",
        title="PSS applied",
        raw_text="The Peak Season Surcharge will be applied next week.",
    )
    db_session.add(advisory)
    await db_session.commit()
    await db_session.refresh(advisory)

    result = await summarize_advisory_async(
        str(advisory.id),
        session_factory=lambda: FakeSessionContext(db_session),
        summarizer_factory=lambda: mock_summarizer,
    )

    # Assert DB is updated
    await db_session.refresh(advisory)
    assert advisory.summary == "A real db-integrated summary."
    assert advisory.impact_severity == "high"
    assert advisory.affected_lanes == ["Asia-Europe"]
    assert result["impact_severity"] == "high"
    mock_summarizer.summarize.assert_awaited_once_with(
        carrier="Maersk",
        title="PSS applied",
        advisory_text="The Peak Season Surcharge will be applied next week.",
    )

@pytest.mark.asyncio
async def test_real_db_missing_advisory(db_session, mock_summarizer):
    fake_id = str(uuid.uuid4())
    with pytest.raises(AdvisoryNotFoundError):
        await summarize_advisory_async(
            fake_id,
            session_factory=lambda: FakeSessionContext(db_session),
            summarizer_factory=lambda: mock_summarizer,
        )

@pytest.mark.asyncio
async def test_real_db_empty_raw_text(db_session, mock_summarizer):
    advisory = CarrierAdvisory(
        carrier="MSC",
        advisory_type="route_suspension",
        title="Suspension",
        raw_text="   ",
    )
    db_session.add(advisory)
    await db_session.commit()
    await db_session.refresh(advisory)

    with pytest.raises(AdvisoryEmptyError):
        await summarize_advisory_async(
            str(advisory.id),
            session_factory=lambda: FakeSessionContext(db_session),
            summarizer_factory=lambda: mock_summarizer,
        )

    mock_summarizer.summarize.assert_not_awaited()

@pytest.mark.asyncio
async def test_real_db_ai_failure_rollback(db_session):
    advisory = CarrierAdvisory(
        carrier="CMACGM",
        advisory_type="blank_sailing",
        title="Blank Sailing Schedule",
        raw_text="Several sailings are blanked.",
    )
    db_session.add(advisory)
    await db_session.commit()
    await db_session.refresh(advisory)

    failing_summarizer = MagicMock()
    failing_summarizer.summarize = AsyncMock(side_effect=AITimeoutError("AI took too long"))

    with pytest.raises(AITimeoutError):
        await summarize_advisory_async(
            str(advisory.id),
            session_factory=lambda: FakeSessionContext(db_session),
            summarizer_factory=lambda: failing_summarizer,
        )

    # Assert DB row is untampered because the transaction was rolled back
    # The adapter attempts to set advisory.summary before commit. The rollback should revert the SQLAlchemy session state.
    await db_session.refresh(advisory)
    assert advisory.summary is None
    assert advisory.impact_severity is None

@pytest.mark.asyncio
async def test_real_db_idempotency(db_session):
    advisory = CarrierAdvisory(
        carrier="Hapag-Lloyd",
        advisory_type="schedule_change",
        title="Schedule change to Asia",
        raw_text="The schedule is changed.",
    )
    db_session.add(advisory)
    await db_session.commit()
    await db_session.refresh(advisory)

    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(
        side_effect=[
            CarrierSummaryOutput(
                summary="First iteration summary.",
                affected_lanes=["L1"],
                impact_severity="low",
                effective_date=None,
            ),
            CarrierSummaryOutput(
                summary="Second iteration summary.",
                affected_lanes=["L1", "L2"],
                impact_severity="medium",
                effective_date=None,
            ),
        ]
    )

    # Run once
    await summarize_advisory_async(
        str(advisory.id),
        session_factory=lambda: FakeSessionContext(db_session),
        summarizer_factory=lambda: summarizer,
    )
    await db_session.refresh(advisory)
    assert advisory.summary == "First iteration summary."

    # Run twice
    await summarize_advisory_async(
        str(advisory.id),
        session_factory=lambda: FakeSessionContext(db_session),
        summarizer_factory=lambda: summarizer,
    )
    await db_session.refresh(advisory)
    assert advisory.summary == "Second iteration summary."
    assert advisory.impact_severity == "medium"
    assert advisory.affected_lanes == ["L1", "L2"]

    assert summarizer.summarize.await_count == 2
