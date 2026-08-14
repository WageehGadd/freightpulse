# %% [markdown]
# # Testing AI-2: Rate Anomaly Detector
# Flat cell-based script for testing Z-score anomaly detection.

# %%
import pandas as pd
import sys
import os

# Add the main project directory to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from tests.fixtures.synthetic_data_generator import all_synthetic_rates
from ai.modules.rate_anomaly_detector import detect_anomalies

def test_normal_conditions():
    lane = 'Shanghai-Europe (Stable)'
    lane_data = all_synthetic_rates[all_synthetic_rates['trade_lane'] == lane].copy()
    lane_data = lane_data.tail(30).copy()
    lane_data.reset_index(drop=True, inplace=True)
    
    rates_series = lane_data['rate_usd']
    result = detect_anomalies(lane, rates_series)
    
    assert result is None, "Expected no anomaly in stable data"

def test_price_spike_anomaly():
    lane = 'Shanghai-Europe (Stable)'
    lane_data = all_synthetic_rates[all_synthetic_rates['trade_lane'] == lane].copy()
    lane_data = lane_data.tail(30).copy()
    lane_data.reset_index(drop=True, inplace=True)
    
    # Inject a massive price spike
    lane_data.loc[lane_data.index[-1], 'rate_usd'] += 900.0
    
    rates_series_spiked = lane_data['rate_usd']
    result = detect_anomalies(lane, rates_series_spiked)
    
    assert result is not None, "Expected anomaly to be detected"
    assert result.alert_type == "rate_spike"
    assert result.z_score > 2.0
    assert result.trade_lane == lane