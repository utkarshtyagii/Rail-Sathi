"""Track Razorpay payment attempts after service completion.

Revision ID: bf2d90b6a431
Revises: 3a0f81544147
Create Date: 2026-10-14 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "bf2d90b6a431"
down_revision = "3a0f81544147"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider_order_id", sa.String(length=80), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=80), nullable=True),
        sa.Column("receipt", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["booking.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_order_id"),
        sa.UniqueConstraint("provider_payment_id"),
        sa.UniqueConstraint("receipt"),
    )
    op.create_index("ix_payment_attempt_booking_id", "payment_attempt", ["booking_id"], unique=False)
    op.create_index("ix_payment_attempt_status", "payment_attempt", ["status"], unique=False)


def downgrade():
    op.drop_index("ix_payment_attempt_status", table_name="payment_attempt")
    op.drop_index("ix_payment_attempt_booking_id", table_name="payment_attempt")
    op.drop_table("payment_attempt")
