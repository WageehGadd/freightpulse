from datetime import date, timedelta

import pandas as pd
import pytest

from ai.modules.rate_anomaly_detector import detect_anomalies
from ai.modules.rate_trend_computer import compute_trend
from ai.schemas.ai_outputs import RateAnomalySchema, RateTrendSchema


class TestStatisticalGoldenCases:
    """Golden tests with mathematically deterministic expected outputs."""

    def test_golden_rising_trend_classification(self):
        """Golden Case 1: Perfect linear rise of $10/day over 30 days."""
        today = date.today()
        rates = [1000.0 + 10.0 * i for i in range(30)]
        dates = [today - timedelta(days=29 - i) for i in range(30)]
        df = pd.DataFrame({"rate_date": dates, "rate_usd": rates})

        result = compute_trend("Golden-Rising", df)

        assert isinstance(result, RateTrendSchema)
        assert result.trend == "rising"
        assert result.slope_per_week == pytest.approx(70.0, abs=0.5)
        assert result.r_squared == pytest.approx(1.0, abs=0.01)
        assert result.avg_30d_usd == pytest.approx(1145.0, abs=1.0)

    def test_golden_stable_identical_rates(self):
        """Golden Case 2: Flat market (zero variance). Must not crash."""
        today = date.today()
        rates = [2500.0] * 30
        dates = [today - timedelta(days=29 - i) for i in range(30)]
        df = pd.DataFrame({"rate_date": dates, "rate_usd": rates})

        result = compute_trend("Golden-Stable", df)

        assert result.trend == "stable"
        assert result.slope_per_week == 0.0
        assert result.r_squared == 0.0

    def test_golden_anomaly_spike_detection(self):
        """Golden Case 3: 29 days of flat data, 1 day of massive spike."""
        rates = pd.Series([2000.0] * 29 + [2500.0])

        result = detect_anomalies("Golden-Spike", rates, threshold=2.5)

        assert isinstance(result, RateAnomalySchema)
        assert result.alert_type == "rate_spike"
        assert result.direction == "up"
        assert result.magnitude_pct == pytest.approx(25.0, abs=0.1)
        assert "spiked" in result.message

    def test_golden_gradual_trend_is_not_anomaly(self):
        """Golden Case 4: Detrending validation. Steady climb != anomaly."""
        rates = pd.Series([1000.0 + 50.0 * i for i in range(30)])

        result = detect_anomalies("Golden-Gradual", rates, threshold=2.5)

        assert result is None, "False Positive: Gradual trend incorrectly flagged!"

    def test_golden_spike_resistant_trend(self):
        """Golden Case 5 (P3 #1): Theil-Sen ignores a +50% last-day spike."""
        today = date.today()
        rates = [1000.0 + 10.0 * i for i in range(30)]
        rates[-1] = round(rates[-1] * 1.5, 2)
        dates = [today - timedelta(days=29 - i) for i in range(30)]
        df = pd.DataFrame({"rate_date": dates, "rate_usd": rates})

        result = compute_trend("Golden-Spike-Resistant", df)

        assert result.trend == "rising"
        assert result.slope_per_week == pytest.approx(70.0, abs=5.0)

    def test_golden_ols_shows_spike_contamination(self):
        """Golden Case 6 (P3 #1): OLS on the same data is distorted (proof)."""
        today = date.today()
        rates = [1000.0 + 10.0 * i for i in range(30)]
        rates[-1] = round(rates[-1] * 1.5, 2)
        dates = [today - timedelta(days=29 - i) for i in range(30)]
        df = pd.DataFrame({"rate_date": dates, "rate_usd": rates})

        result_ols = compute_trend("Golden-OLS", df, method="ols")

        assert result_ols.slope_per_week > 75.0

    def test_golden_volatile_lane_adaptive_prevents_false_alarm(self):
        """Golden Case 7 (P3 #2): Adaptive threshold suppresses volatile false alarms."""
        rates = [2000.0]
        for change in [0.001] * 26 + [0.05, -0.05, 0.045]:
            rates.append(round(rates[-1] * (1 + change), 2))
        series = pd.Series(rates)

        # Adaptive: correctly suppressed (effective threshold = 3.0)
        assert detect_anomalies("Golden-Volatile", series, adaptive=True) is None

        # Legacy fixed 2.5: false alarm — proves the enhancement's value
        legacy = detect_anomalies("Golden-Volatile", series, adaptive=False)
        assert legacy is not None
        assert legacy.alert_type == "rate_spike"
        assert legacy.threshold_used == 2.5

    def test_golden_sustained_movement_pattern(self):
        """Golden Case 8 (P3 #3): Consecutive same-direction moves → sustained event.

        26 quiet days (+0.1%) followed by 3 consecutive +4% days must be
        classified as a sustained movement: duration_days=3 and cumulative
        magnitude ≈ (1.04³ - 1) = +12.49%.
        """
        rates = [2000.0]
        for change in [0.001] * 26 + [0.04, 0.04, 0.04]:
            rates.append(round(rates[-1] * (1 + change), 2))
        series = pd.Series(rates)

        result = detect_anomalies("Golden-Sustained", series, adaptive=False)

        assert result is not None
        assert result.alert_type == "rate_spike"
        assert result.pattern_type == "sustained"
        assert result.duration_days == 3
        assert result.cumulative_magnitude_pct == pytest.approx(12.5, abs=0.5)
        assert "sustained movement" in result.message