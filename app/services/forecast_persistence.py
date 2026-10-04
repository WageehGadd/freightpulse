"""
ForecastPersistenceService — T06

Orchestrates the full forecast generation + persistence pipeline:

  1. Obtain T03 ForecastDataset per series
  2. Run T04 BaselineForecastingService.backtest()
  3. Identify the per-series champion (NOT the global MA(4) default)
  4. Call T04 forecast_next() to generate next-step prediction
  5. Attach backtest evidence, T03 readiness, and T02/T03 freshness
  6. Persist idempotently using uq_rate_forecast_epoch uniqueness policy
  7. Return typed RateForecastRecord artifacts

Idempotency policy:
  Unique key = (source, trade_lane, container_type,
                latest_observation_date, forecast_for_date, model_name, model_version).
  On conflict: UPDATE the existing row in place (re-run same evidence → same result).
  When latest_observation_date advances: a new row is inserted, preserving audit history.

Freshness:
  input_freshness is derived from LATEST OBSERVATION DATE relative to today,
  NOT from generated_at. Regenerating a forecast today from stale source
  observations does NOT change input_freshness to 'fresh'.

No GPT/Azure calls occur in this service.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rate_forecast import RateForecast
from app.models.freight_rate import FreightRate
from app.services.data_quality import DataQualityService
from app.services.baseline_forecasting import BaselineForecastingService
from app.services.forecast_dataset import ForecastDatasetBuilder

logger = logging.getLogger(__name__)

def _determine_freshness(
    latest_obs_date: date, evaluated_at: datetime | None = None
) -> tuple[str, bool]:
    """Reuse T02 source freshness; generated_at is never an input."""
    status, _ = DataQualityService.evaluate_freight_rate_freshness(latest_obs_date, evaluated_at)
    return status, status in ("fresh", "aging")


def _determine_forecast_for_date(latest_obs_date: date, cadence_days: int = 1) -> date:
    """Next local dataset period under the current daily stored-data contract.

    +1 day is hardcoded, not inferred or a claim about external SCFI publication.
    T03's nominal weekly profile is not an observed cadence abstraction. Weekly
    or irregular datasets require revisiting this contract before consumption.
    """
    return latest_obs_date + timedelta(days=cadence_days)


@dataclass
class ForecastGenerationResult:
    attempted: int
    forecasts: List[RateForecast]
    failed: int

    @property
    def generated(self) -> int:
        return len(self.forecasts)

    @property
    def status(self) -> str:
        if self.failed == 0:
            return "success"
        return "partial_success" if self.generated else "failure"


class ForecastPersistenceService:
    """Orchestrates T03 + T04 and persists results as RateForecast rows."""

    def __init__(self, session: AsyncSession, initial_train_size: int = 15):
        self._session = session
        self._builder = ForecastDatasetBuilder(session)
        self._forecaster = BaselineForecastingService(initial_train_size=initial_train_size)

    async def generate_and_persist_all(self) -> ForecastGenerationResult:
        """Complete all enumerated series; report every outcome, including no artifact."""
        profiles = await self._builder.profile_all_series()
        results: List[RateForecast] = []
        failed = 0
        for p in profiles:
            try:
                row = await self.generate_and_persist_series(
                    p.source, p.trade_lane, p.container_type
                )
                if row:
                    results.append(row)
                else:
                    failed += 1
            except Exception:
                failed += 1
                await self._session.rollback()
                logger.exception(
                    "forecast_persistence_failed",
                    extra={
                        "source": p.source,
                        "trade_lane": p.trade_lane,
                        "container_type": p.container_type,
                    },
                )
        return ForecastGenerationResult(attempted=len(profiles), forecasts=results, failed=failed)

    async def generate_and_persist_series(
        self, source: str, trade_lane: str, container_type: str
    ) -> Optional[RateForecast]:
        """
        Generate + persist a forecast for ONE series.

        Uses the per-series T04 champion — NEVER the global MA(4) default.
        """
        dataset = await self._builder.build_dataset(source, trade_lane, container_type)
        if not dataset or len(dataset.observations) == 0:
            logger.warning("forecast_no_dataset", extra={"source": source, "trade_lane": trade_lane})
            return None

        # Run walk-forward backtesting (may raise if history < initial_train_size)
        try:
            report = self._forecaster.backtest(dataset)
        except ValueError as exc:
            logger.warning("forecast_insufficient_history", extra={"series": dataset.metadata.series_id, "error": str(exc)})
            return None

        # Per-series champion is from the backtest report — not the global default
        champion_model = report.champion_model
        champion_result = next(r for r in report.results if r.model_name == champion_model)

        # Generate next-step prediction
        next_fcst = self._forecaster.forecast_next(
            dataset, champion_model, champion_result.metrics.mae
        )

        # Freshness from observation date, NOT from now()
        latest_obs_date = dataset.observations[-1].date
        # Read exact NUMERIC inputs; T03/T04 backtests deliberately use floats.
        monetary_rows = (await self._session.execute(
            select(FreightRate.rate_usd).where(
                FreightRate.source == source,
                FreightRate.trade_lane == trade_lane,
                FreightRate.container_type == container_type,
                FreightRate.rate_date.in_([obs.date for obs in dataset.observations]),
            ).order_by(FreightRate.rate_date.asc())
        )).scalars().all()
        latest_actual_rate = monetary_rows[-1]
        predicted_rate = self._forecaster.predict_rate(champion_model, list(monetary_rows))
        input_freshness, source_eligible = _determine_freshness(latest_obs_date)
        # Fresh source alone cannot promote the historical-only T04 baseline.
        live_eligible = source_eligible and next_fcst.live_decision_eligible

        forecast_for_date = _determine_forecast_for_date(latest_obs_date, cadence_days=1)

        # Upsert: unique on epoch key
        values = dict(
            source=source,
            trade_lane=trade_lane,
            container_type=container_type,
            forecast_for_date=forecast_for_date,
            predicted_rate=predicted_rate.quantize(Decimal("0.01")),
            model_name=champion_model,
            model_version=self._forecaster.MODEL_VERSION,
            forecast_horizon=1,
            latest_observation_date=latest_obs_date,
            latest_actual_rate=latest_actual_rate,
            history_observations=dataset.metadata.observation_count,
            evaluation_points=champion_result.metrics.evaluation_points,
            backtest_mae=champion_result.metrics.mae,
            backtest_rmse=champion_result.metrics.rmse,
            backtest_smape=champion_result.metrics.smape,
            backtest_directional_accuracy=champion_result.metrics.directional_accuracy_pct,
            data_readiness=dataset.metadata.readiness,
            input_freshness=input_freshness,
            live_decision_eligible=live_eligible,
            warning=next_fcst.warning,
        )

        stmt = pg_insert(RateForecast).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_rate_forecast_epoch",
            set_={
                # On re-run of identical evidence, update evidence fields and generated_at
                "predicted_rate": stmt.excluded.predicted_rate,
                "latest_actual_rate": stmt.excluded.latest_actual_rate,
                "generated_at": func.now(),
                "history_observations": stmt.excluded.history_observations,
                "evaluation_points": stmt.excluded.evaluation_points,
                "backtest_mae": stmt.excluded.backtest_mae,
                "backtest_rmse": stmt.excluded.backtest_rmse,
                "backtest_smape": stmt.excluded.backtest_smape,
                "backtest_directional_accuracy": stmt.excluded.backtest_directional_accuracy,
                "data_readiness": stmt.excluded.data_readiness,
                "input_freshness": stmt.excluded.input_freshness,
                "live_decision_eligible": stmt.excluded.live_decision_eligible,
                "warning": stmt.excluded.warning,
            },
        ).returning(RateForecast)

        result = await self._session.execute(stmt.execution_options(populate_existing=True))
        row = result.scalar_one()
        await self._session.commit()
        logger.info(
            "forecast_persisted",
            extra={
                "id": str(row.id),
                "series": dataset.metadata.series_id,
                "model": champion_model,
                "forecast_for_date": str(forecast_for_date),
                "live_eligible": live_eligible,
            },
        )
        return row

    async def get_latest_forecasts(
        self,
        source: Optional[str] = None,
        trade_lane: Optional[str] = None,
        container_type: Optional[str] = None,
    ) -> List[RateForecast]:
        """
        Return the latest forecast per series (highest latest_observation_date).
        Optionally filtered by source / trade_lane / container_type.
        """
        # Keep model artifacts for audit, but select exactly one winner per series.
        ranked = select(
            RateForecast.id,
            func.row_number().over(
                partition_by=(RateForecast.source, RateForecast.trade_lane, RateForecast.container_type),
                order_by=(
                    RateForecast.latest_observation_date.desc(),
                    RateForecast.generated_at.desc(),
                    RateForecast.forecast_for_date.desc(),
                    RateForecast.model_name.asc(),
                    RateForecast.model_version.asc(),
                    RateForecast.id.asc(),
                ),
            ).label("rank"),
        )
        if source is not None:
            ranked = ranked.where(RateForecast.source == source)
        if trade_lane is not None:
            ranked = ranked.where(RateForecast.trade_lane == trade_lane)
        if container_type is not None:
            ranked = ranked.where(RateForecast.container_type == container_type)
        ranked = ranked.subquery()
        stmt = (
            select(RateForecast).join(ranked, RateForecast.id == ranked.c.id)
            .where(ranked.c.rank == 1)
            .order_by(RateForecast.source, RateForecast.trade_lane, RateForecast.container_type)
        )
        # Winner rows may already be loaded before another session regenerates them.
        # Refresh scalar evidence from this query without changing ranking semantics.
        result = await self._session.execute(stmt.execution_options(populate_existing=True))
        return list(result.scalars().all())
