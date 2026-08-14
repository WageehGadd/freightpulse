"""Quick P0 verification script.

Run after seeding data and executing the Celery tasks:
    python verify_p0.py
"""
from ai.database import SessionLocal, RateAlert, RateTrend


def main() -> None:
    db = SessionLocal()
    try:
        print("=== RATE TRENDS ===")
        trends = db.query(RateTrend).all()
        if not trends:
            print("  (no trend rows — run run_daily_trend_computation first)")
        for t in trends:
            print(f"  {t.trade_lane:<35} trend={t.trend:<18} "
                  f"anomaly_flag={t.anomaly_flag} slope_per_week={t.slope_per_week}")

        print("\n=== RATE ALERTS ===")
        alerts = db.query(RateAlert).all()
        if not alerts:
            print("  (no alerts)")
        for a in alerts:
            print(f"  {a.trade_lane:<35} type={a.alert_type:<12} "
                  f"read={a.is_read} msg={a.message}")
    finally:
        db.close()


if __name__ == "__main__":
    main()