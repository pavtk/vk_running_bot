"""Remove the per-registration sport change limit.

Revision ID: e7a2c6f41b90
Revises: d1f6c2a8e407
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a2c6f41b90"
down_revision: Union[str, Sequence[str], None] = "d1f6c2a8e407"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("registrations", "sport_change_used")


def downgrade() -> None:
    op.add_column(
        "registrations",
        sa.Column(
            "sport_change_used",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.alter_column("registrations", "sport_change_used", server_default=None)
