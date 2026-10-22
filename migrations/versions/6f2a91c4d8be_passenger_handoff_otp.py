"""Add expiring passenger handoff codes to bookings."""

from alembic import op
import sqlalchemy as sa


revision = "6f2a91c4d8be"
down_revision = "7d01c4ef26ab"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("booking", sa.Column("handoff_otp_nonce", sa.String(length=64), nullable=True))
    op.add_column("booking", sa.Column("handoff_otp_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "booking",
        sa.Column("handoff_otp_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("booking", sa.Column("handoff_otp_verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("booking", "handoff_otp_verified_at")
    op.drop_column("booking", "handoff_otp_attempts")
    op.drop_column("booking", "handoff_otp_expires_at")
    op.drop_column("booking", "handoff_otp_nonce")
