"""preserve legacy carrier advisory AI source revision

Revision ID: 83b6a5ce207d
Revises: 2fb13d6d5f40
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "83b6a5ce207d"
down_revision = "2fb13d6d5f40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Bridge databases that reached the former back-branch revision path.

    ``9d518c84d359`` is the canonical owner of these columns.  The former
    sibling branch also introduced this revision, so only add a column when a
    database upgraded from that older branch does not already have it.
    """
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("carrier_advisories")
    }

    if "raw_text" not in existing_columns:
        op.add_column("carrier_advisories", sa.Column("raw_text", sa.Text(), nullable=True))
    if "impact_severity" not in existing_columns:
        op.add_column("carrier_advisories", sa.Column("impact_severity", sa.String(), nullable=True))


def downgrade() -> None:
    """Keep columns owned by the canonical predecessor migration intact."""
