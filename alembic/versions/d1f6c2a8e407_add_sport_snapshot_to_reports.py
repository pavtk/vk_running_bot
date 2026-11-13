"""Store the report's sport independently of mutable registration data.

Revision ID: d1f6c2a8e407
Revises: c4e89a7b130d
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f6c2a8e407"
down_revision: Union[str, Sequence[str], None] = "c4e89a7b130d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("sport_id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE reports AS report
        SET sport_id = event_category.sport_id
        FROM registrations AS registration
        JOIN event_categories AS event_category
          ON event_category.id = registration.event_category_id
        WHERE report.registration_id = registration.id
        """
    )
    op.alter_column(
        "reports",
        "sport_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        op.f("ix_reports_sport_id"),
        "reports",
        ["sport_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_reports_sport_id_sports",
        "reports",
        "sports",
        ["sport_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_reports_sport_id_sports",
        "reports",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_reports_sport_id"), table_name="reports")
    op.drop_column("reports", "sport_id")
