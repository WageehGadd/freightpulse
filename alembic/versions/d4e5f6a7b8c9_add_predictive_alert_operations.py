"""Persist tenant-scoped T14 subscriptions, checkpoints and deduplicated events."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("predictive_alert_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(), nullable=False), sa.Column("trade_lane", sa.String(), nullable=False),
        sa.Column("container_type", sa.String(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "source", "trade_lane", "container_type", name="uq_predictive_subscription_series"))
    op.create_table("predictive_alert_checkpoints",
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("predictive_alert_subscriptions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("accepted_token", sa.String(length=64), nullable=False), sa.Column("checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_table("predictive_alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("predictive_alert_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_identity", sa.String(length=64), nullable=False), sa.Column("transition", sa.String(), nullable=False), sa.Column("category", sa.String(), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("subscription_id", "signal_identity", name="uq_predictive_alert_signal"))
    op.create_index("idx_predictive_events_user", "predictive_alert_events", ["user_id", "created_at"])

def downgrade():
    op.drop_index("idx_predictive_events_user", table_name="predictive_alert_events")
    op.drop_table("predictive_alert_events")
    op.drop_table("predictive_alert_checkpoints")
    op.drop_table("predictive_alert_subscriptions")
