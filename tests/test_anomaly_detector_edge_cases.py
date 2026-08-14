import pandas as pd
import pytest

from ai.modules.rate_anomaly_detector import (
    THRESHOLD_NORMAL_LANE,
    THRESHOLD_STABLE_LANE,
    THRESHOLD_VOLATILE_LANE,
    compute_adaptive_threshold,
    detect_anomalies,
)


# ---------------------------------------------------------------------------
# Detector edge cases
# ---------------------------------------------------------------------------
def test_std_zero_returns_none_without_crash():
    """All-identical rates → zero std → no anomaly, no division-by-zero crash."""
    rates = pd.Series([1500.0] * 30)
    assert detect_anomalies("Test-Lane", rates) is None


def test_insufficient_points_returns_none():
    """<14 points → not enough history for a meaningful Z-score."""
    rates = pd.Series([1000.0 + i for i in range(10)])  # 10 < 14
    assert detect_anomalies("Test-Lane", rates) is None


def test_gradual_rising_trend_no_false_positive():
    """A steady +20/day climb must NOT fire an alert (detrending validation)."""
    rates = pd.Series([2000.0 + 20.0 * i for i in range(30)])
    assert detect_anomalies("Test-Lane", rates) is None


def test_sharp_drop_detected_as_rate_drop():
    """A -25% one-day collapse must be detected as rate_drop / direction=down."""
    rates = pd.Series([2000.0] * 29 + [1500.0])
    result = detect_anomalies("Test-Lane", rates)
    assert result is not None
    assert result.alert_type == "rate_drop"
    assert result.direction == "down"
    assert result.magnitude_pct < 0


# ---------------------------------------------------------------------------
# P3 #2: adaptive threshold logic
# ---------------------------------------------------------------------------
def test_adaptive_threshold_volatile_lane_returns_3_0():
    """Fat-tailed history (3 days beyond 2σ out of 29) → stricter threshold."""
    changes = pd.Series([0.001] * 26 + [0.05, -0.05, 0.045])
    assert compute_adaptive_threshold(changes) == THRESHOLD_VOLATILE_LANE


def test_adaptive_threshold_stable_lane_returns_2_0():
    """Zero tail activity + very low volatility → more sensitive threshold."""
    changes = pd.Series([0.001 if i % 2 == 0 else -0.001 for i in range(29)])
    assert compute_adaptive_threshold(changes) == THRESHOLD_STABLE_LANE


def test_adaptive_threshold_normal_lane_returns_base():
    """Gaussian-like history (1 day beyond 2σ out of 29) → tuned base threshold."""
    changes = pd.Series([0.01, -0.01] * 14 + [0.025])
    assert compute_adaptive_threshold(changes) == THRESHOLD_NORMAL_LANE


def test_adaptive_threshold_insufficient_history_returns_base():
    """<14 changes → not enough evidence to adapt → base threshold."""
    changes = pd.Series([0.01] * 10)
    assert compute_adaptive_threshold(changes) == THRESHOLD_NORMAL_LANE


# ---------------------------------------------------------------------------
# P3 #3: multi-day sustained patterns
# ---------------------------------------------------------------------------
def test_sustained_drop_pattern_detected():
    """Three consecutive -4% days → rate_drop classified as sustained."""
    rates = [2000.0]
    for change in [0.001] * 26 + [-0.04, -0.04, -0.04]:
        rates.append(round(rates[-1] * (1 + change), 2))
    series = pd.Series(rates)

    result = detect_anomalies("Test-Sustained-Drop", series, adaptive=False)

    assert result is not None
    assert result.alert_type == "rate_drop"
    assert result.pattern_type == "sustained"
    assert result.duration_days == 3
    assert result.cumulative_magnitude_pct == pytest.approx(-11.5, abs=0.5)


def test_single_day_spike_classified_one_day():
    """An isolated spike after quiet days → one_day pattern, duration 1."""
    rates = pd.Series([2000.0] * 29 + [2500.0])
    result = detect_anomalies("Test-OneDay", rates, adaptive=False)
    assert result is not None
    assert result.pattern_type == "one_day"
    assert result.duration_days == 1