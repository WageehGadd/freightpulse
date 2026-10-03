"""Shared T06/T07 forecast presentation; application-owned numerical evidence."""
from datetime import datetime
from app.services.data_quality import DataQualityService
from app.schemas.forecast import (
    RateForecastResponse, ForecastSeriesSchema, ForecastValueSchema,
    ForecastEvidenceSchema, ForecastProvenanceSchema, ForecastSafetySchema,
)

def to_forecast_response(row, evaluated_at: datetime) -> RateForecastResponse:
    """Map a RateForecast ORM row to the structured API response."""
    current_freshness, _ = DataQualityService.evaluate_freight_rate_freshness(row.latest_observation_date, evaluated_at)
    return RateForecastResponse(
        id=row.id,
        series=ForecastSeriesSchema(
            source=row.source,
            trade_lane=row.trade_lane,
            container_type=row.container_type,
        ),
        forecast=ForecastValueSchema(
            forecast_for_date=row.forecast_for_date,
            predicted_rate=float(row.predicted_rate),
            model=row.model_name,
            model_version=row.model_version,
            horizon=row.forecast_horizon,
        ),
        evidence=ForecastEvidenceSchema(
            history_observations=row.history_observations,
            evaluation_points=row.evaluation_points,
            mae=row.backtest_mae,
            rmse=row.backtest_rmse,
            smape=row.backtest_smape,
            directional_accuracy=row.backtest_directional_accuracy,
            data_readiness=row.data_readiness,
        ),
        provenance=ForecastProvenanceSchema(
            latest_observation_date=row.latest_observation_date,
            latest_actual_rate=float(row.latest_actual_rate),
            input_freshness_at_generation=row.input_freshness,
            current_input_freshness=current_freshness,
            freshness_evaluated_at=evaluated_at,
            generated_at=row.generated_at,
        ),
        safety=ForecastSafetySchema(
            live_decision_eligible=row.live_decision_eligible,
            warning=row.warning,
        ),
    )
