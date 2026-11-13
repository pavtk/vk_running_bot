from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as SyncSession

from app.database.models import (
    Base,
    Category,
    CategorySportDistance,
    Event,
    EventCategory,
    EventType,
    Sport,
)


def test_event_can_offer_multiple_sports_for_same_category():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with SyncSession(engine) as session:
        category = Category(title="18-34")
        running = Sport(title="Бег")
        swimming = Sport(title="Плавание")
        session.add_all([category, running, swimming])
        session.flush()

        session.add_all(
            [
                CategorySportDistance(
                    category=category,
                    sport=running,
                    distance_km=Decimal("5.00"),
                ),
                CategorySportDistance(
                    category=category,
                    sport=swimming,
                    distance_km=Decimal("1.00"),
                ),
            ]
        )
        event = Event(
            title="Тестовое событие",
            starts_on=date(2026, 11, 14),
            ends_on=date(2026, 11, 15),
            event_type=EventType.DISTANCE,
        )
        event.event_categories = [
            EventCategory(
                category=category,
                sport=running,
                distance_km=Decimal("5.00"),
            ),
            EventCategory(
                category=category,
                sport=swimming,
                distance_km=Decimal("1.00"),
            ),
        ]
        session.add(event)
        session.commit()

        options = session.scalars(
            select(EventCategory)
            .order_by(EventCategory.sport_id)
        ).all()

        assert len(options) == 2
        assert {option.category.title for option in options} == {"18-34"}
        assert {option.sport.title for option in options} == {"Бег", "Плавание"}
        assert {option.distance_km for option in options} == {
            Decimal("5.00"),
            Decimal("1.00"),
        }

    engine.dispose()


def test_sport_change_targets_keep_the_original_category():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with SyncSession(engine) as session:
        category = Category(title="Профи")
        other_category = Category(title="Любители")
        running = Sport(title="Бег")
        swimming = Sport(title="Плавание")
        cycling = Sport(title="Велоспорт")
        event = Event(
            title="Смена спорта",
            starts_on=date(2026, 11, 14),
            ends_on=date(2026, 11, 15),
            event_type=EventType.DISTANCE,
        )
        session.add_all(
            [category, other_category, running, swimming, cycling, event]
        )
        session.flush()
        session.add_all(
            [
                EventCategory(
                    event_id=event.id,
                    category_id=category.id,
                    sport_id=running.id,
                    distance_km=Decimal("10"),
                ),
                EventCategory(
                    event_id=event.id,
                    category_id=category.id,
                    sport_id=swimming.id,
                    distance_km=Decimal("2"),
                ),
                EventCategory(
                    event_id=event.id,
                    category_id=other_category.id,
                    sport_id=cycling.id,
                    distance_km=Decimal("20"),
                ),
            ]
        )
        session.flush()
        current = session.scalar(
            select(EventCategory).where(
                EventCategory.category_id == category.id,
                EventCategory.sport_id == running.id,
            )
        )
        assert current is not None

        targets = session.scalars(
            select(EventCategory).where(
                EventCategory.event_id == event.id,
                EventCategory.category_id == current.category_id,
                EventCategory.sport_id != current.sport_id,
            )
        ).all()

        assert [(target.category_id, target.sport_id) for target in targets] == [
            (category.id, swimming.id)
        ]

    engine.dispose()
