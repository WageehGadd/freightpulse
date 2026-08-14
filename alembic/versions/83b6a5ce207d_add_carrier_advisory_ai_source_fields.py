"""add carrier advisory AI source fields

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
    op.add_column("carrier_advisories", sa.Column("raw_text", sa.Text(), nullable=True))
    op.add_column("carrier_advisories", sa.Column("impact_severity", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("carrier_advisories", "impact_severity")
    op.drop_column("carrier_advisories", "raw_text")
