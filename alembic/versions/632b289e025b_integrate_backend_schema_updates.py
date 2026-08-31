"""integrate backend schema updates

Revision ID: 632b289e025b
Revises: 479a586accb0
Create Date: 2026-08-31 04:44:35.439479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '632b289e025b'
down_revision: Union[str, Sequence[str], None] = '479a586accb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # rate_trends
    op.add_column('rate_trends', sa.Column('r_squared', sa.Float(), nullable=True))
    
    # rate_alert_rules
    op.add_column('rate_alert_rules', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    
    # rate_alerts
    op.add_column('rate_alerts', sa.Column('direction', sa.String(), nullable=True))
    op.add_column('rate_alerts', sa.Column('z_score', sa.Float(), nullable=True))
    op.add_column('rate_alerts', sa.Column('latest_rate', sa.Float(), nullable=True))
    op.add_column('rate_alerts', sa.Column('mean_30d', sa.Float(), nullable=True))
    op.add_column('rate_alerts', sa.Column('pattern_type', sa.String(), server_default='one_day', nullable=False))
    op.add_column('rate_alerts', sa.Column('duration_days', sa.Integer(), server_default='1', nullable=False))
    op.add_column('rate_alerts', sa.Column('cumulative_magnitude_pct', sa.Float(), nullable=True))
    op.add_column('rate_alerts', sa.Column('last_event_date', sa.Date(), nullable=True))
    op.add_column('rate_alerts', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    # rate_alerts
    op.drop_column('rate_alerts', 'updated_at')
    op.drop_column('rate_alerts', 'last_event_date')
    op.drop_column('rate_alerts', 'cumulative_magnitude_pct')
    op.drop_column('rate_alerts', 'duration_days')
    op.drop_column('rate_alerts', 'pattern_type')
    op.drop_column('rate_alerts', 'mean_30d')
    op.drop_column('rate_alerts', 'latest_rate')
    op.drop_column('rate_alerts', 'z_score')
    op.drop_column('rate_alerts', 'direction')
    
    # rate_alert_rules
    op.drop_column('rate_alert_rules', 'updated_at')
    
    # rate_trends
    op.drop_column('rate_trends', 'r_squared')
