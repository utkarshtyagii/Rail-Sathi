"""Treat pre-verification porter accounts as applications to review.

Revision ID: c91f5a6d902e
Revises: 2b8eddc6248a
Create Date: 2026-10-14 18:25:00.000000

"""
from alembic import op


revision = "c91f5a6d902e"
down_revision = "2b8eddc6248a"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('UPDATE "user" SET porter_status = \'pending\' WHERE role = \'porter\'')


def downgrade():
    pass
