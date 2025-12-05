# Evaluation Dashboard for LLM Apps

Small FastAPI + PostgreSQL service that stores LLM request logs, evaluates them, and exposes metrics for dashboards and scheduled reports.

## Project structure
- `app/` — FastAPI app, routers, settings, SQLAlchemy models.
- `app/api/metrics.py` — metrics + import endpoints.
- `app/api/admin.py` — management endpoints (refresh materialized view).
- `app/models.py` — `RequestLog` table + `mv_daily_metrics` view mapping.
- `alembic/` — migrations (partitioned table + materialized view).
- `scripts/run_evals.py` — synthetic evaluation generator (used by CI).
- `static/index.html` — Plotly dashboard.
- `.github/workflows/nightly-evals.yml` — nightly scheduled evaluations + upload.

## Configuration
Environment variables (can be placed in `.env`):
- `DATABASE_URL` (required): e.g. `postgresql+asyncpg://user:pass@localhost:5432/evaldb`
- `INGEST_TOKEN` (optional): bearer token required for `/metrics/import` and admin routes.
- `API_HOST` / `API_PORT` (optional): defaults `0.0.0.0:8000`
- `CORS_ORIGINS` (optional): JSON list of allowed origins, default `["*"]`

## Setup & migrations
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```
The initial migration creates a range-partitioned `request_logs` table (monthly partitions for the previous month + next 12) and the `mv_daily_metrics` materialized view.

## Running the API locally
```bash
uvicorn app.main:app --reload --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000}
```
Open `http://localhost:8000` to view the Plotly dashboard. API docs: `http://localhost:8000/docs`.

## API quick reference
- `GET /metrics/requests` — aggregated success rate + p50/p95 latency (filters: `model`, `prompt`, `start`, `end`).
- `GET /metrics/ratings` — average user ratings.
- `GET /metrics/timeseries` — daily metrics (uses `mv_daily_metrics`, falls back to live aggregation).
- `POST /metrics/import` — batch ingest logs (Bearer token required if `INGEST_TOKEN` is set).
- `POST /admin/refresh-materialized` — refresh `mv_daily_metrics` (Bearer token required if `INGEST_TOKEN` is set).

Time filtering: defaults to last 7 days for `/metrics/requests`, 30 days for ratings/timeseries when `start` is omitted.

## Frontend
`static/index.html` uses Plotly to render success rate and latency over time and calls the API via `fetch`. It is GitHub Pages friendly and can also be served by FastAPI (`/static/index.html` and mounted at `/`).

## Running evaluations locally
```bash
python scripts/run_evals.py --prompt onboarding_v5 --model gpt-4.1-mini --limit 25 --output metrics.json
# Optional: post directly to a running API
EVAL_API_BASE=http://localhost:8000 EVAL_API_TOKEN=secret \
python scripts/run_evals.py --prompt onboarding_v5 --model gpt-4.1-mini --limit 25 --post
```
The script writes `metrics.json` compatible with `/metrics/import`.

## Nightly evaluations (GitHub Actions)
`.github/workflows/nightly-evals.yml` runs nightly at 02:00 UTC, generates synthetic metrics via `scripts/run_evals.py`, then uploads to `/metrics/import` using secrets:
- `EVAL_API_BASE` — API base URL
- `EVAL_API_TOKEN` — bearer token matching `INGEST_TOKEN`

## Materialized view maintenance
Run the refresh endpoint or execute:
```bash
psql $DATABASE_URL -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_metrics;"
```
Refresh after imports to keep the timeseries endpoint fast.

## Partition maintenance
The migration creates partitions for ~1 year ahead. Add future partitions periodically (e.g., monthly cron) using:
```sql
CREATE TABLE IF NOT EXISTS request_logs_YYYY_MM PARTITION OF request_logs
FOR VALUES FROM ('YYYY-MM-01') TO ('YYYY-MM-01'::date + INTERVAL '1 month');
```
