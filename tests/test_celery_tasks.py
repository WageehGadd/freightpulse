# %% [markdown]
# # Testing Celery Tasks Locally
# This script executes the Celery task functions synchronously to verify their logic.

# %%
import sys
import os
import logging

# Set up simple logging to see the Celery logger output
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Add the main project directory to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ai.tasks import run_daily_trend_computation, run_daily_anomaly_detection

# %%
def test_tasks():
    print(f"\n{'='*50}\n🧪 1. Testing Trend Computation Task\n{'='*50}")
    # Using .apply() runs the Celery task synchronously in the current thread
    # instead of sending it to a background worker
    trend_result = run_daily_trend_computation.apply()
    if trend_result.successful():
        print(f"✅ Trend Task execution completed with status: {trend_result.result}")
    else:
        print(f"❌ Trend Task failed.")

    print(f"\n{'='*50}\n🧪 2. Testing Anomaly Detection Task\n{'='*50}")
    anomaly_result = run_daily_anomaly_detection.apply()
    if anomaly_result.successful():
        print(f"✅ Anomaly Task execution completed with status: {anomaly_result.result}")
    else:
        print(f"❌ Anomaly Task failed.")

# %%
if __name__ == "__main__":
    test_tasks()