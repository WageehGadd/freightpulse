"""Edge-case tests for ai/modules/rate_trend_computer.py (plan AI-1 testing spec).

Covers: insufficient data, exact minimum (7 points), identical rates, volatile series.
Happy-path tests (stable/rising/falling) live in test_trend_computer.py.
All data here is deterministic — no randomness — so results are reproducible.
"""
from datetime import date, timedelta

import pandas as pd
import pytest

from ai.modules.rate_trend_computer import compute_trend


def _make_df(rates: list[float]) -> pd.DataFrame:
    """Build a [rate_date, rate_usd] DataFrame ending today.

    Mirrors exactly what the Celery task passes after groupby('trade_lane'):
    a frame WITHOUT the trade_lane column.
    """
    today = date.today()
    n = len(rates)
    dates = [today - timedelta(days=n - 1 - i) for i in range(n)]
    return pd.DataFrame({"rate_date": dates, "rate_usd": rates})


def test_insufficient_data_below_seven_points():
    """<7 points must return the 'insufficient_data' label, never a misleading trend."""
    df = _make_df([1000.0, 1010.0, 1020.0])  # 3 points < 7
    result = compute_trend("Test-Lane", df)
    assert result.trend == "insufficient_data"


def test_exactly_seven_points_is_viable():
    """Exactly 7 points is the minimum viable window (plan AI-1 edge case)."""
    # Perfect line: 1000 + 10/day → slope_per_week = 70 → rising
    rates = [1000.0 + 10.0 * i for i in range(7)]
    result = compute_trend("Test-Lane", _make_df(rates))
    assert result.trend == "rising"
    assert result.slope_per_week == pytest.approx(70.0, abs=0.5)


def test_all_identical_rates_classified_stable():
    """All-identical rates (plan AI-1 edge case) → stable, zero slope, no crash."""
    result = compute_trend("Test-Lane", _make_df([1500.0] * 30))
    assert result.trend == "stable"
    assert result.slope_per_week == pytest.approx(0.0, abs=0.01)


def test_volatile_flat_series_stays_stable():
    """High variance with zero real trend must NOT produce rising/falling."""
    # Deterministic sawtooth: alternates 1400/1600 → noisy but flat
    rates = [1400.0 if i % 2 == 0 else 1600.0 for i in range(30)]
    result = compute_trend("Test-Lane", _make_df(rates))
    assert result.trend == "stable"
    assert result.r_squared < 0.3  # noisy data → weak linear fit