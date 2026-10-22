"""Add a unique main administrator account.

Revision ID: b5d4a2c109ef
Revises: a71c2e90f436
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa


revision = "b5d4a2c109ef"
down_revision = "a71c2e90f436"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("is_main_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Preserve existing deployments by making their earliest staff admin the main admin.
    op.execute(
        "UPDATE user SET is_main_admin = 1 "
        "WHERE id = (SELECT id FROM user WHERE role = 'admin' ORDER BY id LIMIT 1)"
    )
    op.create_index(
        "uq_user_one_main_admin",
        "user",
        ["is_main_admin"],
        unique=True,
        sqlite_where=sa.text("is_main_admin = 1"),
        postgresql_where=sa.text("is_main_admin = true"),
    )


def downgrade():
    op.drop_index("uq_user_one_main_admin", table_name="user")
    op.drop_column("user", "is_main_admin")
