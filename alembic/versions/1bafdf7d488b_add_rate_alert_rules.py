"""add_rate_alert_rules

Revision ID: 1bafdf7d488b
Revises: dc23342acfef
Create Date: 2026-08-16 04:05:21.563266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1bafdf7d488b'
down_revision: Union[str, Sequence[str], None] = 'dc23342acfef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create rate_alert_rules
    op.create_table('rate_alert_rules',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('trade_lane', sa.String(), nullable=False),
    sa.Column('alert_type', sa.String(), nullable=False),
    sa.Column('magnitude_pct', sa.Float(), nullable=True),
    sa.Column('target_usd', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_rules_user_active', 'rate_alert_rules', ['user_id', 'is_active'], unique=False)

    # 2. Add columns to rate_alerts. Delete existing stub data to allow non-null if any exists.
    op.execute("DELETE FROM rate_alerts")
    op.add_column('rate_alerts', sa.Column('rule_id', sa.UUID(), nullable=False))
    op.add_column('rate_alerts', sa.Column('evaluation_date', sa.Date(), nullable=False))

    # 3. Add FK
    op.create_foreign_key('fk_rate_alerts_rule_id', 'rate_alerts', 'rate_alert_rules', ['rule_id'], ['id'], ondelete='CASCADE')

    # 4. Add Unique constraint
    op.create_unique_constraint('uq_alert_rule_eval_date', 'rate_alerts', ['rule_id', 'evaluation_date'])


def downgrade() -> None:
    op.drop_constraint('uq_alert_rule_eval_date', 'rate_alerts', type_='unique')
    op.drop_constraint('fk_rate_alerts_rule_id', 'rate_alerts', type_='foreignkey')
    op.drop_column('rate_alerts', 'evaluation_date')
    op.drop_column('rate_alerts', 'rule_id')

    op.drop_index('idx_rules_user_active', table_name='rate_alert_rules')
    op.drop_table('rate_alert_rules')
