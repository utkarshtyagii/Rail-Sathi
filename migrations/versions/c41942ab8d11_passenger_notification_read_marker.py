"""Track when a passenger last viewed booking notifications.

Revision ID: c41942ab8d11
Revises: b5d4a2c109ef
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa


revision = "c41942ab8d11"
down_revision = "b5d4a2c109ef"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("last_notification_read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("user", "last_notification_read_at")
