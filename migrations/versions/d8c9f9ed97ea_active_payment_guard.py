"""Allow only one active payment attempt per booking.

Revision ID: d8c9f9ed97ea
Revises: c62ea045cd14
Create Date: 2026-10-14 19:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d8c9f9ed97ea"
down_revision = "c62ea045cd14"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_payment_attempt_one_active_booking",
        "payment_attempt",
        ["booking_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('creating', 'created', 'authorized', 'processing')"),
        postgresql_where=sa.text("status IN ('creating', 'created', 'authorized', 'processing')"),
    )


def downgrade():
    op.drop_index("uq_payment_attempt_one_active_booking", table_name="payment_attempt")
