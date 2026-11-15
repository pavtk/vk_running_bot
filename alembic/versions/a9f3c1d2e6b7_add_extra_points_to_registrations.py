"""Add extra points to registrations.

Revision ID: a9f3c1d2e6b7
Revises: e7a2c6f41b90
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9f3c1d2e6b7"
down_revision: Union[str, Sequence[str], None] = "e7a2c6f41b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registrations",
        sa.Column(
            "extra_points",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.alter_column(
        "registrations",
        "extra_points",
        existing_type=sa.Integer(),
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("registrations", "extra_points")
