"""Synthetic freight rate data generator for development and testing.

Generates 90 days of synthetic rate data for multiple trade lanes with
different trend patterns (rising, falling, stable) and Gaussian noise.

Two consumption paths:
1. Unit tests import `all_synthetic_rates` (combined DataFrame) — DO NOT REMOVE.
2. `seed_database()` inserts data into freight_rates for Celery tasks, with an
   injected one-day spike so AI-2 has a real anomaly to detect in dev runs.

Usage:
    python -m tests.fixtures.synthetic_data_generator
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ai.database import FreightRate, SessionLocal, init_db


# Trade lane configurations with distinct trend patterns
TRADE_LANES = [
    {
        "name": "Shanghai-Europe (Stable)",
        "base_rate": 1500.0,
        "volatility": 15.0,
        "daily_slope": 0.0,
    },
    {
        "name": "Port Said-Rotterdam (Rising)",
        "base_rate": 1300.0,
        "volatility": 20.0,
        "daily_slope": 5.0,  # +5 USD/day → ~+35/week (clearly rising)
    },
    {
        "name": "Alexandria-Hamburg (Falling)",
        "base_rate": 2500.0,
        "volatility": 25.0,
        "daily_slope": -8.0,  # -8 USD/day → ~-56/week (clearly falling)
    },
]

DAYS_OF_HISTORY = 90
SPIKE_LANE = "Port Said-Rotterdam (Rising)"
SPIKE_MULTIPLIER = 1.18  # +18% one-day spike → guaranteed anomaly (z >> 2.5)
SEED = 42  # deterministic data → reproducible tests and dev runs


def _generate_lane_series(lane_config: dict, days: int = DAYS_OF_HISTORY) -> pd.DataFrame:
    """Generate a synthetic rate series for one trade lane: trend + Gaussian noise."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]

    current = lane_config["base_rate"]
    volatility = lane_config["volatility"]
    daily_slope = lane_config["daily_slope"]

    rates = []
    for _ in range(days):
        current += daily_slope + float(np.random.normal(0, volatility))
        current = max(current, 500.0)  # floor to prevent unrealistic negative rates
        rates.append(round(current, 2))

    return pd.DataFrame({
        "trade_lane": lane_config["name"],
        "rate_date": dates,
        "rate_usd": rates,
    })


def generate_all_synthetic_rates(days: int = DAYS_OF_HISTORY, seed: int = SEED) -> pd.DataFrame:
    """Combined DataFrame [trade_lane, rate_date, rate_usd] for all lanes (no spike).

    Deterministic via fixed seed, and restores global RNG state so importing
    this module has no side effects on other random consumers.
    """
    rng_state = np.random.get_state()
    np.random.seed(seed)
    try:
        all_dfs = [_generate_lane_series(lane, days) for lane in TRADE_LANES]
    finally:
        np.random.set_state(rng_state)
    return pd.concat(all_dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# Module-level exports consumed by unit tests — DO NOT REMOVE OR RENAME
# (tests/fixtures/test_trend_computer.py & test_anomaly_detector.py import this)
# ---------------------------------------------------------------------------
all_synthetic_rates = generate_all_synthetic_rates()


def _inject_spike(df: pd.DataFrame) -> pd.DataFrame:
    """Apply a one-day price spike to the latest row of SPIKE_LANE (for AI-2 e2e tests)."""
    df = df.copy()
    lane_mask = df["trade_lane"] == SPIKE_LANE
    last_idx = df[lane_mask]["rate_date"].idxmax()
    df.loc[last_idx, "rate_usd"] = round(df.loc[last_idx, "rate_usd"] * SPIKE_MULTIPLIER, 2)
    return df


def seed_database(clear_existing: bool = True, inject_spike: bool = True) -> int:
    """Generate synthetic data and insert into freight_rates.

    Args:
        clear_existing: delete all existing freight_rates rows first (reproducible dev).
        inject_spike: add a one-day spike to SPIKE_LANE so anomaly detection
                      has something real to find.

    Returns:
        Number of rows inserted.
    """
    init_db()  # ensure tables exist

    db = SessionLocal()
    try:
        if clear_existing:
            deleted = db.query(FreightRate).delete()
            db.commit()
            print(f"🗑️  Cleared {deleted} existing freight_rates rows")

        combined = generate_all_synthetic_rates()
        if inject_spike:
            combined = _inject_spike(combined)
            print(f"⚡ Injected +{(SPIKE_MULTIPLIER - 1) * 100:.0f}% spike into "
                  f"'{SPIKE_LANE}' (latest day)")

        rows = [
            FreightRate(
                trade_lane=row["trade_lane"],
                rate_date=row["rate_date"],
                rate_usd=row["rate_usd"],
            )
            for _, row in combined.iterrows()
        ]
        db.bulk_save_objects(rows)
        db.commit()

        print("\n📊 Sample rows:")
        print(combined.sample(min(10, len(combined))))
        return len(rows)

    finally:
        db.close()


if __name__ == "__main__":
    count = seed_database()
    print(f"\n✅ Inserted {count} rows into freight_rates. Ready for Celery tasks!")