"""Save the passenger contact number for each booking.

Revision ID: c62ea045cd14
Revises: bf2d90b6a431
Create Date: 2026-10-14 19:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c62ea045cd14"
down_revision = "bf2d90b6a431"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("booking", sa.Column("passenger_phone", sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column("booking", "passenger_phone")
