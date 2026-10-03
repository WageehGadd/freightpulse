"""Shared exact-series state collection; database errors deliberately propagate."""
from datetime import datetime, timezone
from sqlalchemy import select, func
from app.models.freight_rate import FreightRate
from app.schemas.decision import ForecastSnapshot, ForecastState, SeriesIdentity
from app.services.data_quality import DataQualityService
from app.services.forecast_persistence import ForecastPersistenceService


def snapshot_forecast(row):
    """Copy scalar evidence now, before a mutable ORM generation can change."""
    fields = {name: getattr(row, name) for name in (
        "forecast_for_date", "predicted_rate", "model_name", "model_version",
        "forecast_horizon", "latest_observation_date", "latest_actual_rate",
        "history_observations", "evaluation_points", "backtest_mae", "backtest_rmse",
        "backtest_smape", "backtest_directional_accuracy", "data_readiness", "warning", "generated_at")}
    return ForecastSnapshot(forecast_id=row.id,
        series=SeriesIdentity(source=row.source, trade_lane=row.trade_lane, container_type=row.container_type),
        input_freshness_at_generation=row.input_freshness,
        stored_live_decision_eligible=row.live_decision_eligible, **fields)


def freshness_and_eligibility(cutoff, stored_eligible, context_state, evaluated_at):
    freshness, _ = DataQualityService.evaluate_freight_rate_freshness(cutoff, evaluated_at)
    return freshness, bool(stored_eligible and freshness in ("fresh", "aging") and context_state == "current")

class ForecastStateCollector:
    def __init__(self, session):
        self.session = session

    async def collect(self, snapshot, evaluated_at, expected_series=None, generation=None):
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        now = evaluated_at.astimezone(timezone.utc)
        series = snapshot.series
        latest_date = await self.session.scalar(select(func.max(FreightRate.rate_date)).where(
            FreightRate.source == series.source, FreightRate.trade_lane == series.trade_lane,
            FreightRate.container_type == series.container_type))
        # Preserve T07 source-first short circuit, including infrastructure behavior.
        latest = []
        if latest_date is not None and latest_date <= snapshot.latest_observation_date:
            latest = await ForecastPersistenceService(self.session).get_latest_forecasts(
                series.source, series.trade_lane, series.container_type)
        winner = latest[0] if latest else None
        matches = expected_series is None or expected_series == series
        source_superseded = latest_date is not None and latest_date > snapshot.latest_observation_date
        forecast_superseded = (winner is None or winner.id != snapshot.forecast_id or
            winner.generated_at != (generation if generation is not None else snapshot.generated_at))
        state, warning = "current", None
        if not matches:
            state, warning = "series_mismatch", "The forecast does not match the requested series."
        elif latest_date is None:
            state, warning = "source_unavailable", "Matching source observations are unavailable."
        elif source_superseded:
            state, warning = "superseded", "Newer source observations require forecast regeneration."
        elif forecast_superseded:
            state, warning = "superseded", "The selected forecast generation is no longer current."
        freshness, effective = freshness_and_eligibility(snapshot.latest_observation_date,
            snapshot.stored_live_decision_eligible, state, now)
        return ForecastState(series=series, evaluated_at=now, latest_source_date=latest_date,
            latest_forecast_id=winner.id if winner else None,
            latest_forecast_generated_at=winner.generated_at if winner else None,
            series_matches=matches, source_superseded=source_superseded,
            forecast_superseded=forecast_superseded, current_input_freshness=freshness,
            stored_live_decision_eligible=snapshot.stored_live_decision_eligible,
            effective_live_decision_eligible=effective, context_state=state, context_warning=warning)
