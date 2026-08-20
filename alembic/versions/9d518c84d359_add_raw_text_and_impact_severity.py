"""add raw_text and impact_severity

Revision ID: 9d518c84d359
Revises: 9d518c84d358
Create Date: 2026-08-10 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d518c84d359'
down_revision: Union[str, Sequence[str], None] = '9d518c84d358'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("carrier_advisories")
    }

    if "raw_text" not in existing_columns:
        op.add_column(
            "carrier_advisories",
            sa.Column("raw_text", sa.String(), nullable=False, server_default=""),
        )
    if "impact_severity" not in existing_columns:
        op.add_column(
            "carrier_advisories",
            sa.Column("impact_severity", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column('carrier_advisories', 'impact_severity')
    op.drop_column('carrier_advisories', 'raw_text')
