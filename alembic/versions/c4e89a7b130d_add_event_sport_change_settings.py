"""Add per-event sport change settings and one-time registration limit.

Revision ID: c4e89a7b130d
Revises: b1c48f6d2a90
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e89a7b130d"
down_revision: Union[str, Sequence[str], None] = "b1c48f6d2a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "sport_change_open",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "registrations",
        sa.Column(
            "sport_change_used",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.alter_column("events", "sport_change_open", server_default=None)
    op.alter_column("registrations", "sport_change_used", server_default=None)


def downgrade() -> None:
    op.drop_column("registrations", "sport_change_used")
    op.drop_column("events", "sport_change_open")
