"""add route brief outcome fields and query indexes

Revision ID: 2fb13d6d5f40
Revises: 9d518c84d359
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "2fb13d6d5f40"
down_revision = "9d518c84d359"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("route_briefs", sa.Column("recommendation", sa.String(), nullable=True))
    op.add_column("route_briefs", sa.Column("risk_level", sa.String(), nullable=True))
    op.add_column("route_briefs", sa.Column("error_message", sa.String(), nullable=True))

    op.create_index("idx_rates_lane", "freight_rates", ["trade_lane", "rate_date"])
    op.create_index("idx_rates_date", "freight_rates", ["rate_date"])
    op.create_index("idx_rates_source", "freight_rates", ["source", "rate_date"])
    op.create_index("idx_port_code_time", "port_congestion", ["port_code", "measured_at"])
    op.create_index("idx_carrier_published", "carrier_advisories", ["published_at"])
    op.create_index("idx_carrier_type", "carrier_advisories", ["carrier", "advisory_type"])
    op.create_index("idx_trends_lane_date", "rate_trends", ["trade_lane", "computed_date"])
    op.create_index("idx_briefs_user", "route_briefs", ["user_id", "created_at"])
    op.create_index("idx_briefs_status", "route_briefs", ["status"])
    op.create_index("idx_alerts_user_unread", "rate_alerts", ["user_id", "is_read", "created_at"])
    op.create_index("idx_alerts_type", "rate_alerts", ["alert_type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_alerts_type", table_name="rate_alerts")
    op.drop_index("idx_alerts_user_unread", table_name="rate_alerts")
    op.drop_index("idx_briefs_status", table_name="route_briefs")
    op.drop_index("idx_briefs_user", table_name="route_briefs")
    op.drop_index("idx_trends_lane_date", table_name="rate_trends")
    op.drop_index("idx_carrier_type", table_name="carrier_advisories")
    op.drop_index("idx_carrier_published", table_name="carrier_advisories")
    op.drop_index("idx_port_code_time", table_name="port_congestion")
    op.drop_index("idx_rates_source", table_name="freight_rates")
    op.drop_index("idx_rates_date", table_name="freight_rates")
    op.drop_index("idx_rates_lane", table_name="freight_rates")

    op.drop_column("route_briefs", "error_message")
    op.drop_column("route_briefs", "risk_level")
    op.drop_column("route_briefs", "recommendation")
