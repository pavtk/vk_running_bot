"""add missing data constraints

Revision ID: d41c2b9e8a70
Revises: 965ceebd705c
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d41c2b9e8a70"
down_revision: Union[str, Sequence[str], None] = "965ceebd705c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "check_event_type_runs_per_week",
        "events",
        "(event_type = 'runs_per_week' AND runs_per_week IS NOT NULL "
        "AND runs_per_week > 0) OR "
        "(event_type = 'distance' AND runs_per_week IS NULL)",
    )
    op.create_check_constraint(
        "check_event_category_distance_positive",
        "event_categories",
        "distance_km > 0",
    )
    op.drop_constraint(
        "check_event_category_distance_positive",
        "reports",
        type_="check",
    )
    op.create_check_constraint(
        "check_report_distance_positive",
        "reports",
        "distance_km > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "check_report_distance_positive",
        "reports",
        type_="check",
    )
    op.create_check_constraint(
        "check_event_category_distance_positive",
        "reports",
        "distance_km > 0",
    )
    op.drop_constraint(
        "check_event_category_distance_positive",
        "event_categories",
        type_="check",
    )
    op.drop_constraint(
        "check_event_type_runs_per_week",
        "events",
        type_="check",
    )
