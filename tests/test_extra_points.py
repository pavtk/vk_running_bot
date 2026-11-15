from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from app.bot.handlers.extra_points import (
    _extra_points_events_query,
    _extra_points_registrations_query,
    _format_choices,
    _parse_choice_numbers,
    _parse_positive_integer,
)
from app.database.models import (
    Base,
    Category,
    Event,
    EventCategory,
    EventType,
    Registration,
    Sport,
    User,
)


def test_parse_positive_integer_rejects_zero_negative_and_non_integer():
    assert _parse_positive_integer("12") == 12
    assert _parse_positive_integer(" 12 ") == 12
    assert _parse_positive_integer("0") is None
    assert _parse_positive_integer("-2") is None
    assert _parse_positive_integer("2.5") is None
    assert _parse_positive_integer(None) is None


def test_parse_positive_integer_rejects_extremely_long_values():
    assert _parse_positive_integer("9" * 11) is None


def test_parse_choice_numbers_accepts_multiple_numbers_separated_by_commas():
    assert _parse_choice_numbers("1, 2, 4", max_choice=4) == [1, 2, 4]
    assert _parse_choice_numbers(" 2 , 1 ", max_choice=4) == [2, 1]


def test_parse_choice_numbers_rejects_invalid_or_duplicate_selections():
    assert _parse_choice_numbers("", max_choice=4) is None
    assert _parse_choice_numbers("1,,2", max_choice=4) is None
    assert _parse_choice_numbers("1,0", max_choice=4) is None
    assert _parse_choice_numbers("1,5", max_choice=4) is None
    assert _parse_choice_numbers("2,2", max_choice=4) is None
    assert _parse_choice_numbers("1,abc", max_choice=4) is None


def test_format_choices_splits_long_lists_without_dropping_choices():
    chunks = _format_choices(
        [(index, f"Участник {index}") for index in range(1, 400)],
        "Выбери участника:",
    )

    choice_lines = [
        line
        for chunk in chunks
        for line in chunk.splitlines()
        if line[:1].isdigit()
    ]
    assert len(chunks) > 1
    assert choice_lines == [f"{index}. Участник {index}" for index in range(1, 400)]


def test_extra_points_queries_list_only_registered_events_and_order_members():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with SyncSession(engine) as session:
        category = Category(title="Любитель")
        sport = Sport(title="Бег")
        events = [
            Event(
                title="Март",
                starts_on=date(2026, 3, 1),
                ends_on=date(2026, 3, 31),
                event_type=EventType.DISTANCE,
            ),
            Event(
                title="Без участников",
                starts_on=date(2026, 4, 1),
                ends_on=date(2026, 4, 30),
                event_type=EventType.DISTANCE,
            ),
            Event(
                title="Апрель",
                starts_on=date(2026, 4, 1),
                ends_on=date(2026, 4, 30),
                event_type=EventType.DISTANCE,
            ),
        ]
        session.add_all([category, sport, *events])
        session.flush()

        participants = [
            User(vk_id=2, first_name="Борис", last_name="Б"),
            User(vk_id=1, first_name="Анна", last_name="А"),
        ]
        session.add_all(participants)
        session.flush()
        for event in (events[0], events[2]):
            event_category = EventCategory(
                event_id=event.id,
                category_id=category.id,
                sport_id=sport.id,
                distance_km=10,
            )
            session.add(event_category)
            session.flush()
            session.add_all(
                [
                    Registration(
                        user_id=participant.id,
                        event_id=event.id,
                        event_category_id=event_category.id,
                        extra_points=participant.vk_id,
                    )
                    for participant in participants
                ]
            )
        session.commit()

        listed_events = session.execute(_extra_points_events_query()).all()
        april_event = next(row for row in listed_events if row.title == "Апрель")
        registrations = session.execute(
            _extra_points_registrations_query(april_event.id)
        ).all()

    assert [row.title for row in listed_events] == ["Апрель", "Март"]
    assert [(row.first_name, row.last_name, row.extra_points) for row in registrations] == [
        ("Анна", "А", 1),
        ("Борис", "Б", 2),
    ]
