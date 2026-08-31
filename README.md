# FreightPulse AI

FreightPulse AI is a comprehensive AI solution for freight logistics intelligence. This repository contains the AI-A track (Statistical Analysis, Data Validation, Scheduling, and Evaluation Infrastructure).

## Getting Started

### 1. Environment Setup

Copy the example environment file and fill in your values (if any):
```bash
cp .env.example .env
```

Install the required dependencies:
```bash
pip install -r requirements.txt
```

### 2. Database

The project uses SQLAlchemy. By default, it will create an SQLite database in the current directory (`freightpulse.db`). You can override this by setting `DATABASE_URL` in your `.env` file (e.g., to point to PostgreSQL).

### 3. Running Celery

This project uses Celery for background tasks and batch processing.

**Start the Celery Worker:**
```bash
celery -A ai.celery_app worker --loglevel=info
```

**Start the Celery Beat Scheduler (for daily CRON jobs):**
```bash
celery -A ai.celery_app beat --loglevel=info
```

### 4. Running Tests

The project is fully integrated with Pytest. To run all tests (statistical models and evaluation harnesses):

```bash
pytest
```
