"""Store passenger date of birth.

Revision ID: a71c2e90f436
Revises: d8c9f9ed97ea
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa


revision = "a71c2e90f436"
down_revision = "d8c9f9ed97ea"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("user", "date_of_birth")
