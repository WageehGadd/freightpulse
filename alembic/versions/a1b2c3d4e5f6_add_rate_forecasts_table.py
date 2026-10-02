"""add_rate_forecasts_table

Revision ID: a1b2c3d4e5f6
Revises: 7a3b421a2c3d
Create Date: 2026-10-03 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7a3b421a2c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rate_forecasts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        # Series identity
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('trade_lane', sa.String(), nullable=False),
        sa.Column('container_type', sa.String(), nullable=False),
        # Forecast
        sa.Column('forecast_for_date', sa.Date(), nullable=False),
        sa.Column('predicted_rate', sa.Numeric(12, 2), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('forecast_horizon', sa.Integer(), nullable=False, server_default='1'),
        # Input provenance
        sa.Column('latest_observation_date', sa.Date(), nullable=False),
        sa.Column('latest_actual_rate', sa.Numeric(12, 2), nullable=False),
        sa.Column('history_observations', sa.Integer(), nullable=False),
        # Backtest evidence snapshot (captured at generation time)
        sa.Column('evaluation_points', sa.Integer(), nullable=False),
        sa.Column('backtest_mae', sa.Float(), nullable=False),
        sa.Column('backtest_rmse', sa.Float(), nullable=False),
        sa.Column('backtest_smape', sa.Float(), nullable=False),
        sa.Column('backtest_directional_accuracy', sa.Float(), nullable=False),
        # Data quality
        sa.Column('data_readiness', sa.String(), nullable=False),
        # Freshness & safety
        sa.Column('input_freshness', sa.String(), nullable=False),
        sa.Column('live_decision_eligible', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('warning', sa.Text(), nullable=True),
        # Audit
        sa.Column(
            'generated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source', 'trade_lane', 'container_type',
            'latest_observation_date', 'forecast_for_date', 'model_name', 'model_version',
            name='uq_rate_forecast_epoch'
        ),
    )
    op.create_index('idx_forecast_series', 'rate_forecasts', ['source', 'trade_lane', 'container_type'])
    op.create_index('idx_forecast_obs_date', 'rate_forecasts', ['latest_observation_date'])
    op.create_index('idx_forecast_for_date', 'rate_forecasts', ['forecast_for_date'])


def downgrade() -> None:
    op.drop_index('idx_forecast_for_date', table_name='rate_forecasts')
    op.drop_index('idx_forecast_obs_date', table_name='rate_forecasts')
    op.drop_index('idx_forecast_series', table_name='rate_forecasts')
    op.drop_table('rate_forecasts')
