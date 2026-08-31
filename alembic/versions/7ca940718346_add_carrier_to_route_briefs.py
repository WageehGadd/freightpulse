"""add carrier to route_briefs

Revision ID: 7ca940718346
Revises: 39b9ba168b2e
Create Date: 2026-08-16 06:57:44.216480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ca940718346'
down_revision: Union[str, Sequence[str], None] = '39b9ba168b2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('route_briefs', sa.Column('carrier', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('route_briefs', 'carrier')
