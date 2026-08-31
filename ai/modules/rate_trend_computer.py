"""Rate Trend Computer (AI-1).

Computes 7-day and 30-day rolling trends for freight rates.

Uses the Theil-Sen estimator (robust regression) by default — resistant to
spike contamination, so a single-day anomaly cannot distort the trend slope.
OLS (classical linregress) remains available via method="ols" for comparison.

Enhancement log:
- v2 (Sprint 5): Default switched from OLS to Theil-Sen to prevent spikes from
  inflating/deflating the computed trend (plan §AI-1 Future Improvements).
- v1: OLS via scipy.stats.linregress + NaN guards.
"""
import math
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import linregress, theilslopes

from ai.schemas.ai_outputs import RateTrendSchema

# Regression method: "theil_sen" (robust, default) or "ols" (classical)
RegressionMethod = Literal["theil_sen", "ols"]


def compute_trend(
    trade_lane: str,
    rates: pd.DataFrame,
    method: RegressionMethod = "theil_sen",
) -> RateTrendSchema:
    """Compute statistical trend for a single trade lane.

    Args:
        trade_lane: Name of the trade lane.
        rates: DataFrame with columns [rate_date, rate_usd], sorted by date ASC.
               Minimum 7 data points required; 30 preferred.
        method: "theil_sen" (default) is robust to single-day spikes;
                "ols" is classical least-squares (kept for comparison/tests).

    Returns:
        RateTrendSchema containing computed averages, changes, and trend classification.
    """
    rates = rates.dropna(subset=["rate_usd"]).copy()

    if len(rates) < 7:
        return RateTrendSchema(
            trade_lane=trade_lane,
            computed_date=date.today(),
            avg_7d_usd=0.0,
            avg_30d_usd=0.0,
            change_7d_pct=0.0,
            change_30d_pct=0.0,
            trend="insufficient_data",
            slope_per_week=0.0,
            r_squared=0.0,
        )

    avg_7d = rates.tail(7)["rate_usd"].mean()
    avg_30d = rates["rate_usd"].mean()

    x = np.arange(len(rates), dtype=float)
    y = rates["rate_usd"].to_numpy(dtype=float)

    # --- Regression -------------------------------------------------------
    if method == "theil_sen":
        # Robust: median of all pairwise slopes → resistant to outliers
        slope, intercept, _, _ = theilslopes(y, x)
    else:
        slope, intercept, _, _, _ = linregress(x, y)

    # Degenerate-case guards (e.g., all identical rates)
    if math.isnan(slope):
        slope = 0.0
    if math.isnan(intercept):
        intercept = float(y[0])

    slope_per_week = round(slope * 7, 2)

    # R² measured against the fitted line (works for both methods).
    # Clamped to [0, 1] since non-OLS fits can yield negative pseudo-R².
    predicted = intercept + slope * x
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_sq = 0.0 if ss_tot == 0 else max(0.0, round(1 - ss_res / ss_tot, 4))

    # --- Classification ---------------------------------------------------
    threshold = avg_30d * 0.01
    if slope_per_week > threshold:
        trend = "rising"
    elif slope_per_week < -threshold:
        trend = "falling"
    else:
        trend = "stable"

    # --- Percentage changes ------------------------------------------------
    current = rates.iloc[-1]["rate_usd"]
    prev_7d = rates.iloc[-8]["rate_usd"] if len(rates) >= 8 else rates.iloc[0]["rate_usd"]
    prev_30d = rates.iloc[0]["rate_usd"]

    change_7d_pct = round((current - prev_7d) / prev_7d * 100, 1) if prev_7d != 0 else 0.0
    change_30d_pct = round((current - prev_30d) / prev_30d * 100, 1) if prev_30d != 0 else 0.0

    return RateTrendSchema(
        trade_lane=trade_lane,
        computed_date=date.today(),
        avg_7d_usd=round(avg_7d, 2),
        avg_30d_usd=round(avg_30d, 2),
        change_7d_pct=change_7d_pct,
        change_30d_pct=change_30d_pct,
        trend=trend,
        slope_per_week=slope_per_week,
        r_squared=r_sq,
    )