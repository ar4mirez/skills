"""create links

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "links",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code", name="links_code_key"),
    )


def downgrade() -> None:
    op.drop_table("links")
