"""Track support ticket resolution time for account notifications."""

from alembic import op
import sqlalchemy as sa


revision = "4c2e8a1d9f70"
down_revision = "e8b4c2d91a70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("support_request") as batch_op:
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_support_request_closed_at", ["closed_at"], unique=False)


def downgrade():
    with op.batch_alter_table("support_request") as batch_op:
        batch_op.drop_index("ix_support_request_closed_at")
        batch_op.drop_column("closed_at")
