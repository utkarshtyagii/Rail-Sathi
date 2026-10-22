"""Add explicit porter online/offline availability.

Revision ID: 92e6b2f3c210
Revises: c41942ab8d11
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa


revision = "92e6b2f3c210"
down_revision = "c41942ab8d11"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "porter_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    user_table = sa.table(
        "user",
        sa.column("role", sa.String()),
        sa.column("porter_status", sa.String()),
        sa.column("active", sa.Boolean()),
        sa.column("porter_available", sa.Boolean()),
    )
    op.execute(
        user_table.update()
        .where(
            user_table.c.role == "porter",
            user_table.c.porter_status == "verified",
            user_table.c.active.is_(True),
        )
        .values(porter_available=True)
    )


def downgrade():
    op.drop_column("user", "porter_available")
