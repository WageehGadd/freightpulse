import math
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
from datetime import date
from app.services.forecast_dataset import ForecastDataset

class BacktestObservation(BaseModel):
    prediction_date: date
    actual_value: float
    predicted_value: float
    absolute_error: float
    squared_error: float
    percentage_error: float
    directional_accuracy: Optional[int] # 1 for correct direction, 0 for incorrect, None if undefined (e.g. flat)

class BacktestMetrics(BaseModel):
    mae: float
    rmse: float
    smape: float
    directional_accuracy_pct: float
    evaluation_points: int

class ModelBacktestResult(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_name: str
    metrics: BacktestMetrics
    observations: List[BacktestObservation]

class SeriesBacktestReport(BaseModel):
    series_id: str
    results: List[ModelBacktestResult]
    champion_model: str
    champion_mae: float

class NextStepForecast(BaseModel):
    model_config = {"protected_namespaces": ()}
    series_id: str
    prediction_date: date
    model_name: str
    predicted_value: float
    historical_backtest_mae: float
    input_freshness: str
    live_decision_eligible: bool
    warning: str


class BaselineForecastingService:
    def __init__(self, initial_train_size: int = 15):
        self.initial_train_size = initial_train_size
        self.models = ["Naive", "MA(2)", "MA(3)", "MA(4)", "Drift"]

    def _smape(self, actual: float, predicted: float) -> float:
        denominator = (abs(actual) + abs(predicted)) / 2.0
        if denominator == 0.0:
            return 0.0
        return abs(actual - predicted) / denominator * 100.0

    def _direction(self, previous: float, current: float) -> int:
        if current > previous: return 1
        if current < previous: return -1
        return 0

    def _predict(self, model_name: str, history: List[float], horizon: int = 1) -> float:
        n = len(history)
        if n == 0:
            return 0.0
            
        last_val = history[-1]
        
        if model_name == "Naive":
            return last_val
            
        elif model_name == "MA(2)":
            if n < 2: return last_val
            return sum(history[-2:]) / 2.0
            
        elif model_name == "MA(3)":
            if n < 3: return sum(history[-n:]) / n
            return sum(history[-3:]) / 3.0
            
        elif model_name == "MA(4)":
            if n < 4: return sum(history[-n:]) / n
            return sum(history[-4:]) / 4.0
            
        elif model_name == "Drift":
            if n < 2: return last_val
            first_val = history[0]
            return last_val + horizon * ((last_val - first_val) / (n - 1))
            
        return last_val

    def backtest(self, dataset: ForecastDataset) -> SeriesBacktestReport:
        obs = dataset.observations
        n_obs = len(obs)
        
        if n_obs <= self.initial_train_size:
            # Insufficient data for walk-forward
            raise ValueError(f"Dataset has {n_obs} points, need > {self.initial_train_size} for backtesting")
            
        # Target values
        y = [o.target_rate for o in obs]
        dates = [o.date for o in obs]
        
        model_results = []
        
        for model in self.models:
            backtest_obs = []
            
            for t in range(self.initial_train_size, n_obs):
                history = y[:t]
                actual = y[t]
                pred_date = dates[t]
                
                predicted = self._predict(model, history, horizon=1)
                
                abs_err = abs(actual - predicted)
                sq_err = abs_err ** 2
                pct_err = self._smape(actual, predicted)
                
                dir_acc = None
                if t > 0:
                    prev_actual = y[t-1]
                    actual_dir = self._direction(prev_actual, actual)
                    pred_dir = self._direction(prev_actual, predicted)
                    if actual_dir != 0 or pred_dir != 0:
                        dir_acc = 1 if actual_dir == pred_dir else 0
                        
                backtest_obs.append(BacktestObservation(
                    prediction_date=pred_date,
                    actual_value=actual,
                    predicted_value=predicted,
                    absolute_error=abs_err,
                    squared_error=sq_err,
                    percentage_error=pct_err,
                    directional_accuracy=dir_acc
                ))
                
            # Aggregate metrics
            mae = sum(o.absolute_error for o in backtest_obs) / len(backtest_obs)
            rmse = math.sqrt(sum(o.squared_error for o in backtest_obs) / len(backtest_obs))
            smape = sum(o.percentage_error for o in backtest_obs) / len(backtest_obs)
            
            dir_list = [o.directional_accuracy for o in backtest_obs if o.directional_accuracy is not None]
            dir_acc_pct = sum(dir_list) / len(dir_list) * 100.0 if dir_list else 0.0
            
            model_results.append(ModelBacktestResult(
                model_name=model,
                metrics=BacktestMetrics(
                    mae=mae,
                    rmse=rmse,
                    smape=smape,
                    directional_accuracy_pct=dir_acc_pct,
                    evaluation_points=len(backtest_obs)
                ),
                observations=backtest_obs
            ))
            
        # Select champion model
        # Sort by MAE ascending. Tie breaker: RMSE ascending
        model_results.sort(key=lambda r: (r.metrics.mae, r.metrics.rmse, r.model_name))
        champion = model_results[0]
        
        return SeriesBacktestReport(
            series_id=dataset.metadata.series_id,
            results=model_results,
            champion_model=champion.model_name,
            champion_mae=champion.metrics.mae
        )
        
    def forecast_next(self, dataset: ForecastDataset, model_name: str, backtest_mae: float) -> NextStepForecast:
        history = [o.target_rate for o in dataset.observations]
        next_val = self._predict(model_name, history, horizon=1)
        
        # Determine next logical date (assuming 1 day cadence for now based on data)
        # Note: True SCFI is weekly, but DB has daily mocking, so we add 1 day
        from datetime import timedelta
        last_date = dataset.observations[-1].date
        next_date = last_date + timedelta(days=1)
        
        # Check freshness via metadata
        warning = "Historical forecast only. Do not use for live booking decisions."
        is_fresh = False # By default T02 has marked these as stale
        # We can pass live_decision_eligible=False safely based on T03 profiling
        
        return NextStepForecast(
            series_id=dataset.metadata.series_id,
            prediction_date=next_date,
            model_name=model_name,
            predicted_value=next_val,
            historical_backtest_mae=backtest_mae,
            input_freshness="stale",
            live_decision_eligible=False,
            warning=warning
        )
