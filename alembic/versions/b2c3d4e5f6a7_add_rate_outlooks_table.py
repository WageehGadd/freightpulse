"""Add grounded rate outlook artifacts, preserving legacy RateTrend columns."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("rate_outlooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trend_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rate_trends.id"), nullable=False),
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rate_forecasts.id"), nullable=False),
        sa.Column("forecast_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("outlook_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("narration_input", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("trend_id", "forecast_id", "forecast_generated_at", "prompt_version", name="uq_rate_outlook_generation"))
    op.create_index("idx_outlook_trend", "rate_outlooks", ["trend_id"])
    op.create_index("idx_outlook_forecast", "rate_outlooks", ["forecast_id"])

def downgrade():
    op.drop_index("idx_outlook_forecast", table_name="rate_outlooks")
    op.drop_index("idx_outlook_trend", table_name="rate_outlooks")
    op.drop_table("rate_outlooks")
