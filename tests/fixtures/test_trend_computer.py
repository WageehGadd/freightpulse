# %% [markdown]
# # Testing AI-1: Rate Trend Computer
# This notebook/script tests the linear regression algorithm using our generated synthetic data.

# %%
import pandas as pd
# Add the main project directory to Python path so we can import our modules
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import the synthetic data we just created
from tests.fixtures.synthetic_data_generator import all_synthetic_rates

# Import the core logic and schemas
from ai.modules.rate_trend_computer import compute_trend
from ai.schemas.ai_outputs import RateTrendSchema

# %%
def test_compute_trend_stable():
    lane = 'Shanghai-Europe (Stable)'
    lane_data = all_synthetic_rates[all_synthetic_rates['trade_lane'] == lane].tail(30).copy()
    lane_data.reset_index(drop=True, inplace=True)
    
    result: RateTrendSchema = compute_trend(lane, lane_data)
    
    assert result.trend == "stable", f"Expected stable trend, got {result.trend}"
    assert result.trade_lane == lane

def test_compute_trend_rising():
    lane = 'Port Said-Rotterdam (Rising)'
    lane_data = all_synthetic_rates[all_synthetic_rates['trade_lane'] == lane].tail(30).copy()
    lane_data.reset_index(drop=True, inplace=True)
    
    result: RateTrendSchema = compute_trend(lane, lane_data)
    
    assert result.trend == "rising", f"Expected rising trend, got {result.trend}"
    assert result.slope_per_week > 0

def test_compute_trend_falling():
    lane = 'Alexandria-Hamburg (Falling)'
    lane_data = all_synthetic_rates[all_synthetic_rates['trade_lane'] == lane].tail(30).copy()
    lane_data.reset_index(drop=True, inplace=True)
    
    result: RateTrendSchema = compute_trend(lane, lane_data)
    
    assert result.trend == "falling", f"Expected falling trend, got {result.trend}"
    assert result.slope_per_week < 0