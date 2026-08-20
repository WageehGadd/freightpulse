import sys
from pathlib import Path

# --- Path shim: ensure project root is importable ----------------------------
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ------------------------------------------------------------------------------

import numpy as np
import pandas as pd

from ai.modules.rate_anomaly_detector import detect_anomalies


def _evaluate_strategy(rates_series, is_anomaly, days, detector_fn) -> dict:
    """Slide a 30-day window across the year and score one detection strategy."""
    tp, fp, fn = 0, 0, 0
    for i in range(30, days):
        window = rates_series.iloc[i - 30 : i]
        expected_anomaly = is_anomaly[i - 1]
        detected = detector_fn(window) is not None

        if expected_anomaly and detected:
            tp += 1
        elif expected_anomaly and not detected:
            fn += 1
        elif not expected_anomaly and detected:
            fp += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "Precision": precision, "Recall": recall, "F1": f1}


def run_threshold_experiment() -> None:
    np.random.seed(42)  # Reproducible experiment
    days = 365
    base_rate = 2000.0
    noise_std = 25.0

    # 1. Base random walk + daily noise
    rates = np.cumsum(np.random.normal(0, 5, days)) + base_rate
    rates += np.random.normal(0, noise_std, days)

    # 2. Inject 20 known anomalies after day 60 (clean 30-day windows at start)
    anomaly_indices = np.random.choice(range(60, days), size=20, replace=False)
    is_anomaly = np.zeros(days, dtype=bool)
    for idx in anomaly_indices:
        is_anomaly[idx] = True
        rates[idx] += noise_std * 6 if np.random.rand() > 0.5 else -noise_std * 6

    rates_series = pd.Series(rates)
    print("🔬 Running Threshold Tuning Experiment (365 days, 20 injected anomalies)...\n")

    results = []

    # 3a. Fixed thresholds — adaptive DISABLED for a fair comparison
    for thresh in [1.5, 2.0, 2.5, 3.0, 3.5]:
        metrics = _evaluate_strategy(
            rates_series, is_anomaly, days,
            lambda window, t=thresh: detect_anomalies(
                "Experiment-Lane", window, threshold=t, adaptive=False
            ),
        )
        results.append({"Strategy": f"Fixed z={thresh}", **metrics})

    # 3b. Adaptive strategy (P3 Enhancement #2)
    metrics = _evaluate_strategy(
        rates_series, is_anomaly, days,
        lambda window: detect_anomalies("Experiment-Lane", window, adaptive=True),
    )
    results.append({"Strategy": "ADAPTIVE (2.0/2.5/3.0)", **metrics})

    # 4. Markdown report
    print("## 📊 Anomaly Detection Threshold Tuning Report")
    print("| Strategy | TP | FP | FN | Precision | Recall | F1-Score |")
    print("|:---------|:--:|:--:|:--:|:---------:|:------:|:--------:|")
    for r in results:
        print(f"| **{r['Strategy']}** | {r['TP']} | {r['FP']} | {r['FN']} "
              f"| {r['Precision']:.1%} | {r['Recall']:.1%} | {r['F1']:.1%} |")

    print("\n💡 Compare the ADAPTIVE row against Fixed z=2.5: adaptive should cut")
    print("   false positives on volatile windows while preserving recall.")


if __name__ == "__main__":
    run_threshold_experiment()