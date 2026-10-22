"""Store optional pickup pins and current participant GPS fixes."""

from alembic import op
import sqlalchemy as sa


revision = "7d01c4ef26ab"
down_revision = "92e6b2f3c210"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("booking", sa.Column("pickup_latitude", sa.Float(), nullable=True))
    op.add_column("booking", sa.Column("pickup_longitude", sa.Float(), nullable=True))
    op.create_table(
        "booking_live_location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("is_sharing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["booking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", "user_id", name="uq_booking_live_location_participant"),
    )
    op.create_index("ix_booking_live_location_booking_id", "booking_live_location", ["booking_id"])
    op.create_index("ix_booking_live_location_user_id", "booking_live_location", ["user_id"])


def downgrade():
    op.drop_index("ix_booking_live_location_user_id", table_name="booking_live_location")
    op.drop_index("ix_booking_live_location_booking_id", table_name="booking_live_location")
    op.drop_table("booking_live_location")
    op.drop_column("booking", "pickup_longitude")
    op.drop_column("booking", "pickup_latitude")
