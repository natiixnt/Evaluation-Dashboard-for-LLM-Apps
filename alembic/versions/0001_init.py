"""initial schema with partitioned request_logs and daily metrics MV"""

from __future__ import annotations

from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def _month_start(dt: date, offset: int = 0) -> date:
    month = dt.month - 1 + offset
    year = dt.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _create_partition(conn, start: date) -> None:
    end_month = _month_start(start, 1)
    name = f"request_logs_{start:%Y_%m}"
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE IF NOT EXISTS {name}
            PARTITION OF request_logs
            FOR VALUES FROM ('{start.isoformat()}') TO ('{end_month.isoformat()}');
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at timestamptz NOT NULL DEFAULT now(),
                model text NOT NULL,
                prompt_version text NOT NULL,
                success boolean NOT NULL,
                latency_ms integer NOT NULL,
                user_rating integer,
                error_code text,
                metadata jsonb
            ) PARTITION BY RANGE (created_at);
            """
        )
    )

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_request_logs_created_at ON request_logs (created_at)"))
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_request_logs_model_prompt_date "
            "ON request_logs (model, prompt_version, created_at DESC)"
        )
    )
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_request_logs_model ON request_logs (model)"))

    today = date.today().replace(day=1)
    for offset in range(-1, 13):
        _create_partition(conn, _month_start(today, offset))

    conn.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_metrics AS
            SELECT
                model,
                prompt_version,
                date_trunc('day', created_at)::date AS date,
                count(*) AS total,
                sum(CASE WHEN success THEN 1 ELSE 0 END) AS success,
                avg(latency_ms)::float AS avg_latency_ms,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)::float AS p50_latency,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::float AS p95_latency
            FROM request_logs
            GROUP BY model, prompt_version, date_trunc('day', created_at);
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_daily_metrics_keys
            ON mv_daily_metrics (model, prompt_version, date);
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS mv_daily_metrics"))

    today = date.today().replace(day=1)
    for offset in range(-1, 13):
        name = f"request_logs_{_month_start(today, offset):%Y_%m}"
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))

    conn.execute(sa.text("DROP TABLE IF EXISTS request_logs"))
