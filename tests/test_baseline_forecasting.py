import pytest
from datetime import date, timedelta
from app.services.baseline_forecasting import BaselineForecastingService, NextStepForecast
from app.services.forecast_dataset import ForecastDataset, ForecastDatasetMetadata, ForecastObservation

@pytest.fixture
def forecasting_service():
    # Use initial window of 3 for testing
    return BaselineForecastingService(initial_train_size=3)

def create_mock_dataset(rates: list[float]) -> ForecastDataset:
    obs = []
    base_date = date(2026, 1, 1)
    for i, r in enumerate(rates):
        obs.append(ForecastObservation(
            date=base_date + timedelta(days=i),
            target_rate=r,
            features={}
        ))
    
    meta = ForecastDatasetMetadata(
        series_id="test_series",
        source="test",
        trade_lane="test",
        container_type="20ft",
        start_date=base_date,
        end_date=base_date + timedelta(days=len(rates)-1),
        observation_count=len(rates),
        readiness="MINIMAL",
        quality_warnings=[],
        feature_names=[]
    )
    return ForecastDataset(metadata=meta, observations=obs)

def test_naive_forecast(forecasting_service):
    # [100, 110, 120] -> next should be 120
    assert forecasting_service._predict("Naive", [100.0, 110.0, 120.0]) == 120.0

def test_moving_averages(forecasting_service):
    history = [10.0, 20.0, 30.0, 40.0]
    assert forecasting_service._predict("MA(2)", history) == 35.0 # (30+40)/2
    assert forecasting_service._predict("MA(3)", history) == 30.0 # (20+30+40)/3
    assert forecasting_service._predict("MA(4)", history) == 25.0 # (10+20+30+40)/4

def test_drift_forecast(forecasting_service):
    # Drift formula: last + horizon * (last - first) / (n - 1)
    # history = [10, 20, 30, 40]
    # n=4, first=10, last=40
    # expected = 40 + 1 * (40 - 10) / 3 = 40 + 30/3 = 50
    assert forecasting_service._predict("Drift", [10.0, 20.0, 30.0, 40.0]) == 50.0

def test_walk_forward_evaluation(forecasting_service):
    # k=3. 
    # obs: [100, 110, 120, 130, 140]
    dataset = create_mock_dataset([100.0, 110.0, 120.0, 130.0, 140.0])
    report = forecasting_service.backtest(dataset)
    
    # 2 evaluation points: predict 130 (idx 3) using [100,110,120], then 140 (idx 4) using [100,110,120,130]
    naive_res = next(r for r in report.results if r.model_name == "Naive")
    assert naive_res.metrics.evaluation_points == 2
    
    # Eval 1: actual 130, predicted 120 -> abs_err 10, pct_err = |130-120| / ((130+120)/2) * 100 = 10 / 125 * 100 = 8.0
    # Eval 2: actual 140, predicted 130 -> abs_err 10, pct_err = |140-130| / ((140+130)/2) * 100 = 10 / 135 * 100 = 7.407...
    assert naive_res.observations[0].actual_value == 130.0
    assert naive_res.observations[0].predicted_value == 120.0
    assert naive_res.observations[0].absolute_error == 10.0
    assert naive_res.metrics.mae == 10.0

def test_leakage_protection(forecasting_service):
    # If future observation is extreme, earlier predictions shouldn't change
    ds1 = create_mock_dataset([100.0, 110.0, 120.0, 130.0, 140.0])
    ds2 = create_mock_dataset([100.0, 110.0, 120.0, 130.0, 9999.0]) # Extreme future
    
    rep1 = forecasting_service.backtest(ds1)
    rep2 = forecasting_service.backtest(ds2)
    
    naive1 = next(r for r in rep1.results if r.model_name == "Naive")
    naive2 = next(r for r in rep2.results if r.model_name == "Naive")
    
    # The first evaluation point (predicting 130 using history up to 120) must be IDENTICAL
    assert naive1.observations[0].predicted_value == naive2.observations[0].predicted_value
    assert naive1.observations[0].predicted_value == 120.0

def test_insufficient_data(forecasting_service):
    # k=3, we provide exactly 3. No evaluation points available
    ds = create_mock_dataset([100.0, 110.0, 120.0])
    with pytest.raises(ValueError, match="need > 3 for backtesting"):
        forecasting_service.backtest(ds)

def test_model_selection_deterministic(forecasting_service):
    ds = create_mock_dataset([100.0, 100.0, 100.0, 100.0, 100.0])
    rep = forecasting_service.backtest(ds)
    # All models will predict 100 and have MAE=0
    # Tie breaking by name alphabetically should select Drift as champion
    assert rep.champion_model == "Drift"
    assert rep.champion_mae == 0.0
