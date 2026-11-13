"""Add sports and category-specific sport distances.

Revision ID: b1c48f6d2a90
Revises: d41c2b9e8a70
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c48f6d2a90"
down_revision: Union[str, Sequence[str], None] = "d41c2b9e8a70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sports",
        sa.Column("title", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title"),
    )
    op.execute(
        "INSERT INTO sports (title, created_at) "
        "VALUES ('Бег', CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "category_sport_distances",
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("sport_id", sa.Integer(), nullable=False),
        sa.Column(
            "distance_km",
            sa.Numeric(precision=6, scale=2),
            nullable=True,
            comment="Фиксированная дистанция для категории и вида спорта.",
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "distance_km IS NULL OR distance_km > 0",
            name="check_category_sport_distance_positive",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "category_id", "sport_id",
            name="unique_category_sport_distance",
        ),
    )
    op.create_index(
        op.f("ix_category_sport_distances_category_id"),
        "category_sport_distances",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_category_sport_distances_sport_id"),
        "category_sport_distances",
        ["sport_id"],
        unique=False,
    )

    op.add_column(
        "event_categories",
        sa.Column("sport_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE event_categories "
        "SET sport_id = (SELECT id FROM sports WHERE title = 'Бег')"
    )
    op.execute(
        """
        INSERT INTO category_sport_distances
            (category_id, sport_id, distance_km, created_at)
        SELECT ec.category_id, s.id,
               CASE WHEN COUNT(DISTINCT ec.distance_km) = 1
                    THEN MIN(ec.distance_km)
                    ELSE NULL
               END,
               CURRENT_TIMESTAMP
        FROM event_categories ec
        CROSS JOIN sports s
        WHERE s.title = 'Бег'
        GROUP BY ec.category_id, s.id
        """
    )
    op.alter_column(
        "event_categories",
        "sport_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        op.f("ix_event_categories_sport_id"),
        "event_categories",
        ["sport_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_event_categories_sport_id_sports",
        "event_categories",
        "sports",
        ["sport_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "unique_event_category", "event_categories", type_="unique"
    )
    op.create_unique_constraint(
        "unique_event_category_sport",
        "event_categories",
        ["event_id", "category_id", "sport_id"],
    )
    op.alter_column(
        "event_categories",
        "distance_km",
        existing_type=sa.Numeric(precision=6, scale=2),
        comment=(
            "Снимок дистанции категории и вида спорта на момент добавления "
            "к событию."
        ),
        existing_nullable=False,
    )


def downgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            "SELECT event_id, category_id FROM event_categories "
            "GROUP BY event_id, category_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade: an event has multiple sports in one category."
        )

    op.drop_constraint(
        "unique_event_category_sport", "event_categories", type_="unique"
    )
    op.create_unique_constraint(
        "unique_event_category",
        "event_categories",
        ["event_id", "category_id"],
    )
    op.alter_column(
        "event_categories",
        "distance_km",
        existing_type=sa.Numeric(precision=6, scale=2),
        comment=(
            "Для event_type=runs_per_week — минимальная дистанция категории; "
            "для event_type=distance — целевая дистанция категории."
        ),
        existing_nullable=False,
    )
    op.drop_constraint(
        "fk_event_categories_sport_id_sports",
        "event_categories",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_event_categories_sport_id"), table_name="event_categories"
    )
    op.drop_column("event_categories", "sport_id")
    op.drop_index(
        op.f("ix_category_sport_distances_sport_id"),
        table_name="category_sport_distances",
    )
    op.drop_index(
        op.f("ix_category_sport_distances_category_id"),
        table_name="category_sport_distances",
    )
    op.drop_table("category_sport_distances")
    op.drop_table("sports")
