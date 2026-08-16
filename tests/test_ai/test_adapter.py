from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.adapter import (
    AdvisoryEmptyError,
    AdvisoryNotFoundError,
    AdvisoryRepository,
    CarrierSummarizerAdapter,
)
from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.openai_client import AITimeoutError, AIValidationError
from app.schemas.ai_outputs import CarrierSummaryOutput


class MockAdvisoryRecord:
    def __init__(self, id, carrier, title, raw_text):
        self.id = id
        self.carrier = carrier
        self.title = title
        self.raw_text = raw_text
        self.summary = None
        self.advisory_type = "source_classification"
        self.affected_lanes = None
        self.effective_date = None
        self.impact_severity = None


@pytest.fixture
def mock_repository():
    repo = MagicMock(spec=AdvisoryRepository)
    repo.get_by_id = AsyncMock()
    repo.commit = AsyncMock()
    repo.rollback = AsyncMock()
    return repo


@pytest.fixture
def mock_summarizer():
    summarizer = MagicMock(spec=CarrierSummarizer)
    summarizer.summarize = AsyncMock()
    return summarizer


@pytest.fixture
def adapter(mock_repository, mock_summarizer):
    return CarrierSummarizerAdapter(repository=mock_repository, summarizer=mock_summarizer)


@pytest.mark.asyncio
async def test_summarize_and_save_success(adapter, mock_repository, mock_summarizer):
    advisory_id = 1
    mock_advisory = MockAdvisoryRecord(
        id=advisory_id,
        carrier="CarrierA",
        title="Title A",
        raw_text="Some valid raw text"
    )

    mock_repository.get_by_id.return_value = mock_advisory

    mock_output = CarrierSummaryOutput(
        summary="Test summary over ten chars",
        affected_lanes=["LANE1"],
        impact_severity="high",
    )
    mock_summarizer.summarize.return_value = mock_output

    result = await adapter.summarize_and_save(advisory_id)

    assert result == mock_output
    mock_summarizer.summarize.assert_called_once_with(
        carrier="CarrierA",
        title="Title A",
        advisory_text="Some valid raw text",
    )
    mock_repository.commit.assert_called_once()
    assert mock_advisory.summary == "Test summary over ten chars"
    assert mock_advisory.advisory_type == "source_classification"
    assert mock_advisory.affected_lanes == ["LANE1"]
    assert mock_advisory.impact_severity == "high"


@pytest.mark.asyncio
async def test_summarize_not_found(adapter, mock_repository, mock_summarizer):
    mock_repository.get_by_id.return_value = None

    with pytest.raises(AdvisoryNotFoundError, match="not found"):
        await adapter.summarize_and_save(99)

    mock_summarizer.summarize.assert_not_called()
    mock_repository.commit.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_empty_text(adapter, mock_repository, mock_summarizer):
    mock_advisory = MockAdvisoryRecord(
        id=2,
        carrier="CarrierB",
        title="Title B",
        raw_text="   "
    )
    mock_repository.get_by_id.return_value = mock_advisory

    with pytest.raises(AdvisoryEmptyError, match="empty raw text"):
        await adapter.summarize_and_save(2)

    mock_summarizer.summarize.assert_not_called()
    mock_repository.commit.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_ai_timeout(adapter, mock_repository, mock_summarizer):
    mock_advisory = MockAdvisoryRecord(
        id=3,
        carrier="CarrierC",
        title="Title C",
        raw_text="Valid text"
    )
    mock_repository.get_by_id.return_value = mock_advisory

    mock_summarizer.summarize.side_effect = AITimeoutError("Timeout")

    with pytest.raises(AITimeoutError):
        await adapter.summarize_and_save(3)

    mock_repository.commit.assert_not_called()
    mock_repository.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_ai_validation_failure(adapter, mock_repository, mock_summarizer):
    mock_advisory = MockAdvisoryRecord(
        id=4,
        carrier="CarrierD",
        title="Title D",
        raw_text="Valid text"
    )
    mock_repository.get_by_id.return_value = mock_advisory

    mock_summarizer.summarize.side_effect = AIValidationError("Validation error")

    with pytest.raises(AIValidationError):
        await adapter.summarize_and_save(4)

    mock_repository.commit.assert_not_called()
    mock_repository.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_unexpected_exception(adapter, mock_repository, mock_summarizer):
    mock_advisory = MockAdvisoryRecord(
        id=5,
        carrier="CarrierE",
        title="Title E",
        raw_text="Valid text"
    )
    mock_repository.get_by_id.return_value = mock_advisory

    mock_summarizer.summarize.side_effect = RuntimeError("Broken logic")

    with pytest.raises(RuntimeError):
        await adapter.summarize_and_save(5)

    mock_repository.commit.assert_not_called()
    mock_repository.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_db_commit_failure(adapter, mock_repository, mock_summarizer):
    mock_advisory = MockAdvisoryRecord(
        id=6,
        carrier="CarrierF",
        title="Title F",
        raw_text="Valid text"
    )
    mock_repository.get_by_id.return_value = mock_advisory

    mock_output = CarrierSummaryOutput(
        summary="Test summary over ten chars",
        affected_lanes=["LANE1"],
        impact_severity="high",
    )
    mock_summarizer.summarize.return_value = mock_output

    mock_repository.commit.side_effect = Exception("DB disconnected")

    with pytest.raises(Exception, match="DB disconnected"):
        await adapter.summarize_and_save(6)

    mock_repository.rollback.assert_called_once()


@pytest.mark.asyncio
@patch("app.ai.adapter.logger")
async def test_summarize_logging_safety(mock_logger, adapter, mock_repository, mock_summarizer):
    sensitive_text = "Super secret advisory text for VIP"
    mock_advisory = MockAdvisoryRecord(
        id=7,
        carrier="CarrierG",
        title="Title G",
        raw_text=sensitive_text
    )
    mock_repository.get_by_id.return_value = mock_advisory

    mock_summarizer.summarize.side_effect = RuntimeError("Broken logic")

    with pytest.raises(RuntimeError):
        await adapter.summarize_and_save(7)

    mock_logger.exception.assert_called_once()
    log_args = mock_logger.exception.call_args.args
    log_msg = log_args[0]

    assert sensitive_text not in log_msg
    for arg in log_args[1:]:
        assert sensitive_text not in str(arg)
