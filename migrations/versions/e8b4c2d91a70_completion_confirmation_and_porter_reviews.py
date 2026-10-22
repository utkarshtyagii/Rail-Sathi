"""Add completion confirmation OTPs and passenger porter reviews."""

from alembic import op
import sqlalchemy as sa


revision = "e8b4c2d91a70"
down_revision = "6f2a91c4d8be"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "porter_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("passenger_id", sa.Integer(), nullable=False),
        sa.Column("porter_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_porter_review_rating_range"),
        sa.ForeignKeyConstraint(["booking_id"], ["booking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passenger_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["porter_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id"),
    )
    op.create_index("ix_porter_review_passenger_id", "porter_review", ["passenger_id"], unique=False)
    op.create_index("ix_porter_review_porter_id", "porter_review", ["porter_id"], unique=False)


def downgrade():
    op.drop_index("ix_porter_review_porter_id", table_name="porter_review")
    op.drop_index("ix_porter_review_passenger_id", table_name="porter_review")
    op.drop_table("porter_review")
