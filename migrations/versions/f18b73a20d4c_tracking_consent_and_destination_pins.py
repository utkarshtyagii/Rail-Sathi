"""Persist tracking opt-out and optional destination coordinates."""

from alembic import op
import sqlalchemy as sa


revision = "f18b73a20d4c"
down_revision = "4c2e8a1d9f70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("booking") as batch_op:
        batch_op.add_column(sa.Column("destination_latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("destination_longitude", sa.Float(), nullable=True))
    with op.batch_alter_table("booking_live_location") as batch_op:
        batch_op.add_column(sa.Column("sharing_opted_out", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade():
    with op.batch_alter_table("booking_live_location") as batch_op:
        batch_op.drop_column("sharing_opted_out")
    with op.batch_alter_table("booking") as batch_op:
        batch_op.drop_column("destination_longitude")
        batch_op.drop_column("destination_latitude")
