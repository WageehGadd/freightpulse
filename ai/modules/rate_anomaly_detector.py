import math

import pandas as pd

from ai.schemas.ai_outputs import RateAnomalySchema

# --- Adaptive threshold configuration (P3 #2) --------------------------------
GAUSSIAN_TAIL_EXPECTATION = 0.046
THRESHOLD_STABLE_LANE = 2.0
THRESHOLD_NORMAL_LANE = 2.5
THRESHOLD_VOLATILE_LANE = 3.0
STABLE_LANE_STD_MAX = 0.005

# --- Multi-day pattern configuration (P3 #3) ---------------------------------
SUSTAINED_MIN_DAYS = 2
SUSTAINED_SOFT_THRESHOLD = 0.01  # min daily move (1%) to count toward a run

MIN_POINTS_FOR_DETECTION = 14
MIN_POINTS_FOR_ADAPTIVE = 14


def compute_adaptive_threshold(
    daily_changes: pd.Series,
    base_threshold: float = THRESHOLD_NORMAL_LANE,
) -> float:
    """Adapt the detection threshold to the lane's empirical tail behavior.

    - Fraction of days with |z| > 2 well above the Gaussian expectation (~4.6%)
      → fat-tailed / volatile → stricter threshold (3.0)
    - Zero tail activity AND very low absolute volatility
      → genuinely quiet → more sensitive threshold (2.0)
    - Otherwise → the tuned base threshold (2.5)
    """
    if len(daily_changes) < MIN_POINTS_FOR_ADAPTIVE:
        return base_threshold

    std_change = daily_changes.std()
    if std_change == 0 or math.isnan(std_change):
        return base_threshold

    z_history = (daily_changes - daily_changes.mean()).abs() / std_change
    tail_frequency = float((z_history > 2.0).mean())

    if tail_frequency > GAUSSIAN_TAIL_EXPECTATION * 1.5:
        return THRESHOLD_VOLATILE_LANE
    if tail_frequency == 0.0 and std_change <= STABLE_LANE_STD_MAX:
        return THRESHOLD_STABLE_LANE
    return base_threshold


def _detect_sustained_pattern(daily_changes: pd.Series, direction: str) -> tuple[int, float]:
    """Count consecutive same-direction moves ending on the latest day (P3 #3).

    Walks backward from the most recent daily change, counting days that moved
    in the same direction by more than SUSTAINED_SOFT_THRESHOLD. The detected
    day itself is always counted (duration >= 1).

    Args:
        daily_changes: Series of daily pct_change values (already dropna'd).
        direction: "up" or "down" (direction of the detected anomaly).

    Returns:
        (duration_days, cumulative_magnitude_pct) for the consecutive run.
    """
    sign = 1.0 if direction == "up" else -1.0
    duration = 0
    cumulative_factor = 1.0

    for change in reversed(daily_changes.tolist()):
        if duration == 0 or sign * change > SUSTAINED_SOFT_THRESHOLD:
            duration += 1
            cumulative_factor *= (1.0 + change)
        else:
            break

    return duration, (cumulative_factor - 1.0) * 100.0


def detect_anomalies(
    trade_lane: str,
    rates: pd.Series,
    threshold: float = THRESHOLD_NORMAL_LANE,
    adaptive: bool = False,
) -> RateAnomalySchema | None:
    """Detect a rate anomaly for a single trade lane.

    Args:
        trade_lane: Name of the trade lane.
        rates: Series of rate_usd values sorted by date ASC (last 30 days).
        threshold: Base Z-score threshold (fallback when adaptive).
        adaptive: Enable per-lane adaptive thresholds (production opts in).

    Returns:
        RateAnomalySchema when an anomaly is detected, None otherwise.
    """
    if len(rates) < MIN_POINTS_FOR_DETECTION:
        return None

    daily_changes = rates.pct_change().dropna()

    mean_change = daily_changes.mean()
    std_change = daily_changes.std()
    if std_change == 0 or math.isnan(std_change):
        return None

    effective_threshold = (
        compute_adaptive_threshold(daily_changes, base_threshold=threshold)
        if adaptive
        else threshold
    )

    latest_change = daily_changes.iloc[-1]
    z_score = (latest_change - mean_change) / std_change

    if abs(z_score) > effective_threshold:
        direction = "up" if z_score > 0 else "down"
        alert_type = "rate_spike" if direction == "up" else "rate_drop"

        latest_rate = float(rates.iloc[-1])
        previous_rate = float(rates.iloc[-2])
        magnitude_pct = ((latest_rate - previous_rate) / previous_rate) * 100

        # P3 #3: multi-day pattern detection
        duration_days, cumulative_pct = _detect_sustained_pattern(daily_changes, direction)
        pattern_type = "sustained" if duration_days >= SUSTAINED_MIN_DAYS else "one_day"

        sign = "+" if direction == "up" else ""
        action = "spiked" if direction == "up" else "dropped"
        if pattern_type == "sustained":
            cum_sign = "+" if cumulative_pct >= 0 else ""
            message = (
                f"{trade_lane} FCL rates {action} {cum_sign}{cumulative_pct:.0f}% "
                f"over {duration_days} days (sustained movement)."
            )
        else:
            message = f"{trade_lane} FCL rates {action} {sign}{magnitude_pct:.0f}% in one day."

        return RateAnomalySchema(
            trade_lane=trade_lane,
            alert_type=alert_type,
            message=message,
            magnitude_pct=round(magnitude_pct, 1),
            direction=direction,
            z_score=round(z_score, 2),
            latest_rate=latest_rate,
            mean_30d=round(float(rates.mean()), 2),
            threshold_used=effective_threshold,
            pattern_type=pattern_type,
            duration_days=duration_days,
            cumulative_magnitude_pct=round(cumulative_pct, 1),
        )
    return None