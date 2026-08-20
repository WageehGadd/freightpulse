# FreightPulse AI — Specification Deviations & Architectural Decisions

This document records the intentional design improvements and architectural deviations made between the initial `AI_IMPLEMENTATION_PLAN.md` specification and the production FreightPulse platform implementation.

---

## 1. Regression Algorithm: OLS → Theil-Sen Estimator

* **Original Specification:** Classical Ordinary Least Squares (OLS) linear regression (`scipy.stats.linregress`) to calculate rate trend slopes.
* **Actual Implementation:** Non-parametric Theil-Sen median slope estimator (`scipy.stats.theilslopes`).
* **Rationale:** OLS is sensitive to outliers. A single-day freight rate spike or data entry error heavily distorts the slope in a 30-day window. Theil-Sen calculates the median of all pairwise slopes, making the trend calculation robust against single-day price anomalies.
* **Status:** **Intentional. Permanent.** (OLS remains available as `method="ols"` for statistical comparison tests).

---

## 2. Trend Sensitivity Threshold: 1% → 5% Weekly Change

* **Original Specification:** 1% weekly rate change threshold for classifying trends into `rising` / `falling`.
* **Actual Implementation:** 5% weekly relative rate change threshold (`threshold = avg_30d * 0.05`).
* **Rationale:** Global freight rates naturally fluctuate 1–3% week-over-week due to currency adjustments and fuel surcharges. A 1% threshold caused normal baseline market noise to be misclassified as active trends. A 5% threshold accurately isolates meaningful market movements.
* **Status:** **Intentional. Permanent.**

---

## 3. Anomaly Detection: Simple Z-Score → Detrended Z-Score + Multi-Day Tracking

* **Original Specification:** Standard Z-score computed directly on raw daily freight rates (`z = (rate - mean) / std`).
* **Actual Implementation:** Detrended Z-score calculated on daily percentage changes (`rates.pct_change()`), combined with adaptive Z-score thresholds (2.0 to 3.0) and multi-day sustained event tracking (`sustained` vs `one_day`).
* **Rationale:** On trade lanes experiencing a strong linear trend, simple Z-scores flag everyday price progression as anomalies. Computing Z-scores on detrended daily changes isolates true unexpected price shocks. Multi-day tracking groups consecutive same-direction moves into a single alert event rather than spamming users with daily duplicate alerts.
* **Status:** **Intentional. Permanent.**

---

## 4. PDF Generation Engine: WeasyPrint → ReportLab

* **Original Specification:** WeasyPrint HTML-to-PDF conversion engine for Route Brief PDF exports.
* **Actual Implementation:** Native ReportLab PDF generation (`app/services/pdf_generator.py`).
* **Rationale:** WeasyPrint requires complex system-level C libraries (`cairo`, `pango`, `gdk-pixbuf`) that introduce platform compatibility issues across macOS, Linux, and lightweight Docker containers (`alpine`/`slim`). ReportLab is a pure Python library that builds deterministically in all container and deployment environments without system dependencies.
* **Status:** **Intentional. Permanent.**

---

## 5. Rate Outlook Persistence: Stateless API → DB & Cache Persistence

* **Original Specification:** Rate Outlook specified as a stateless endpoint generating AI narration on the fly without database side effects.
* **Actual Implementation:** Rate Outlook results persist narrative output (`outlook_text`, `recommendation`, `confidence`) directly to the `rate_trends` database model, paired with a 24-hour Redis cache.
* **Rationale:** Regenerating LLM narratives on every HTTP GET request incurs unnecessary OpenAI API costs and latency (2–4s per request). Persisting the generated outlook to the database and caching in Redis ensures instant API responses (< 50ms) and avoids duplicate LLM spend for identical trend queries.
* **Status:** **Intentional. Permanent.**

---

## 6. Celery Schedule: Multiple Individual Crons → Unified Daily Pipeline at 02:00 UTC

* **Original Specification:** Independent Celery Beat cron schedules running scrapers, trend computation, anomaly detection, and outlook generation at separate times.
* **Actual Implementation:** Single daily master orchestration pipeline (`trigger_daily_pipeline` at 02:00 UTC) with Redis distributed locking (`pipeline_lock:{target_date}`).
* **Rationale:** Independent cron schedules risked race conditions where trend calculations ran before rate ingestion completed, or anomaly detection ran on stale trend data. The unified pipeline enforces sequential execution (Ingestion ➔ Trend Computation ➔ Anomaly Detection ➔ Rate Outlook Generation) with Redis lock protection against duplicate worker execution.
* **Status:** **Intentional. Permanent.**

---

## 7. Dual Database Access Layer: Asynchronous App vs Synchronous Celery

* **Original Specification:** Single unified database access pattern.
* **Actual Implementation:**
  - **Asynchronous App Layer (`app/database.py`):** `create_async_engine` using `postgresql+asyncpg://` for FastAPI HTTP endpoints.
  - **Synchronous AI/Celery Layer (`ai/database.py`):** `create_engine` using `postgresql+psycopg2://` (with automated driver fallback) for synchronous background tasks.
* **Rationale:** Celery task workers run in synchronous process pools. Calling async SQLAlchemy engines inside synchronous Celery workers causes event loop blocking and `MissingGreenlet` exceptions. Separating the sync DB driver for background tasks and the async driver for FastAPI endpoints maintains strict concurrency safety and driver compatibility across both runtimes.
* **Status:** **Intentional. Permanent.**
