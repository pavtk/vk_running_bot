from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from app.bot.handlers.cancel import cancel_labeler
from app.bot.handlers.registration import start_registration
from app.bot.handlers.report import parse_report_distance
from app.bot.handlers.states import ReportState
from app.bot.handlers.stats import (
    _aggregate_general_report_rows,
    _calculate_general_report_score,
    _count_fulfilled_weekly_norms,
    _event_participants_query,
    _format_event_participants,
    _format_general_report_table,
    _general_event_report_query,
    _general_report_weekly_rows_query,
    _split_general_report_messages,
    _sort_general_report_categories,
    start_general_event_report,
)
from app.database.models import (
    Base,
    Category,
    Event,
    EventCategory,
    EventType,
    Registration,
    Report,
    Sport,
    User,
)
from app.service import get_or_create_user, get_vk_profile
from app.database.service import (
    event_is_registration_available,
    event_is_report_available,
)


def test_parse_report_distance_accepts_comma_and_dot():
    assert parse_report_distance("#отчет 10,5") == "10.50"
    assert parse_report_distance("#отчет 10.5") == "10.50"
    assert parse_report_distance("#отчет 10.50") == "10.50"
    assert parse_report_distance("#отчёт 10,5") == "10.50"
    assert parse_report_distance("#ОТЧЁТ 10,5") == "10.50"
    assert parse_report_distance("#ОТЧЕТ 10,5") == "10.50"


def test_parse_report_distance_rejects_invalid_format():
    try:
        parse_report_distance("#отчет 10.567")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for >2 decimal places")


def test_general_report_aggregates_category_across_sports():
    participants = _aggregate_general_report_rows(
        [
            (1, "Участник", "Бег", 2, Decimal("12.50"), 4),
            (1, "Участник", "Велоспорт", 1, Decimal("30.00"), 4),
            (2, "Без отчётов", None, 0, Decimal("0.00"), 0),
        ]
    )

    assert participants[1]["training_count"] == 3
    assert participants[1]["distance_by_sport"] == {
        "Бег": Decimal("12.50"),
        "Велоспорт": Decimal("30.00"),
    }
    assert participants[2]["training_count"] == 0
    assert participants[1]["extra_points"] == 4


def test_general_report_categories_are_sorted_by_id_not_title():
    categories = {
        3: SimpleNamespace(title="Новичок"),
        1: SimpleNamespace(title="Профи"),
        2: SimpleNamespace(title="Любитель"),
    }

    assert [
        (category_id, category.title)
        for category_id, category in _sort_general_report_categories(categories)
    ] == [
        (1, "Профи"),
        (2, "Любитель"),
        (3, "Новичок"),
    ]


def test_general_report_table_shows_each_participant_training_count_and_sports():
    table = _format_general_report_table(
        [
            {
                "name": "Участник",
                "training_count": 4,
                "distance_by_sport": {
                    "Бег": Decimal("7.00"),
                    "Велосипед": Decimal("24.50"),
                },
                "weekly_norm_weeks": 0,
            }
        ]
    )

    assert table == (
        "1. Участник, 4 трен., Бег: 7.00 км, Велосипед: 24.50 км, "
        "19.25 условных км, Балл. за норм.: 0, "
        "Доп. Баллы: 0, Всего баллов: 0"
    )
    assert "Всего тренировок" not in table
    assert "Километраж по видам спорта:" not in table


def test_general_report_counts_fulfilled_weekly_norms():
    rows = [
        (1, datetime(2026, 1, 5, 10, tzinfo=timezone.utc)),
        (1, datetime(2026, 1, 6, 10, tzinfo=timezone.utc)),
        (1, datetime(2026, 1, 7, 10, tzinfo=timezone.utc)),
        (1, datetime(2026, 1, 12, 10, tzinfo=timezone.utc)),
        (1, datetime(2026, 1, 13, 10, tzinfo=timezone.utc)),
        (2, datetime(2026, 1, 5, 10, tzinfo=timezone.utc)),
        (2, datetime(2026, 1, 6, 10, tzinfo=timezone.utc)),
    ]

    fulfilled_norms = _count_fulfilled_weekly_norms(
        rows,
        event_starts_on=date(2026, 1, 5),
        through_date=date(2026, 1, 18),
        runs_per_week=3,
        report_timezone=timezone.utc,
    )

    assert fulfilled_norms == {1: 1, 2: 0}


def test_general_report_converts_weekly_norms_to_points():
    table = _format_general_report_table(
        [
            {
                "name": "Участник",
                "training_count": 6,
                "distance_by_sport": {"Бег": Decimal("12.50")},
                "weekly_norm_weeks": 2,
                "extra_points": 5,
            }
        ]
    )

    assert table == (
        "1. Участник, 6 трен., Бег: 12.50 км, "
        "12.50 условных км, Балл. за норм.: 6, "
        "Доп. Баллы: 5, Всего баллов: 11"
    )


def test_event_participants_list_is_numbered_with_category_and_sport():
    assert _format_event_participants(
        [
            ("Ада Лавлейс", "Профи", "Бег"),
            ("Павел Ткаченко", "Любитель", "Велосипед"),
        ]
    ) == (
        "1. Ада Лавлейс, Профи, Бег\n"
        "2. Павел Ткаченко, Любитель, Велосипед"
    )


def test_event_participants_list_shows_empty_event_message():
    assert "нет зарегистрированных участников" in _format_event_participants([])


def test_event_participants_query_returns_registrants_in_category_order():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with SyncSession(engine) as session:
        beginner = Category(title="Новичок")
        pro = Category(title="Профи")
        running = Sport(title="Бег")
        event = Event(
            title="Участники",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 1, 31),
            event_type=EventType.DISTANCE,
        )
        event.event_categories = [
            EventCategory(
                category=beginner,
                sport=running,
                distance_km=Decimal("5.00"),
            ),
            EventCategory(
                category=pro,
                sport=running,
                distance_km=Decimal("10.00"),
            ),
        ]
        session.add_all(
            [
                event,
                User(vk_id=1, first_name="Павел", last_name="Ткаченко"),
                User(vk_id=2, first_name="Ада", last_name="Лавлейс"),
            ]
        )
        session.flush()
        beginner_ec = session.query(EventCategory).filter_by(
            category_id=beginner.id
        ).one()
        pro_ec = session.query(EventCategory).filter_by(
            category_id=pro.id
        ).one()
        pavel = session.query(User).filter_by(vk_id=1).one()
        ada = session.query(User).filter_by(vk_id=2).one()
        session.add_all(
            [
                Registration(
                    user_id=pavel.id,
                    event_id=event.id,
                    event_category_id=pro_ec.id,
                ),
                Registration(
                    user_id=ada.id,
                    event_id=event.id,
                    event_category_id=beginner_ec.id,
                ),
            ]
        )
        session.flush()

        rows = session.execute(_event_participants_query(event.id)).all()

    assert rows == [
        ("Ада", "Лавлейс", "Новичок", "Бег"),
        ("Павел", "Ткаченко", "Профи", "Бег"),
    ]
    engine.dispose()


def test_general_report_score_uses_sport_factors_and_rounds_half_up():
    score = _calculate_general_report_score(
        {
            "Бег": Decimal("7.00"),
            "Велосипед": Decimal("24.50"),
            "Лыжи": Decimal("10.00"),
            "Скандинавская ходьба": Decimal("3.00"),
            "Плавание": Decimal("100.00"),
        }
    )

    assert score == Decimal("31.24")
    assert _calculate_general_report_score(
        {"Велосипед": Decimal("0.01")}
    ) == Decimal("0.01")


def test_general_report_is_split_under_message_limit_without_losing_rows():
    rows = [
        f"{index}. Участник {index}, 4 трен., Бег: 7.00 км"
        for index in range(1, 21)
    ]

    messages = _split_general_report_messages(
        "Отчёт по событию\nКатегория: Профи",
        "\n".join(rows),
        max_length=200,
    )

    assert len(messages) > 1
    assert all(len(message) <= 200 for message in messages)
    assert [
        message.split("\n[Часть ")[-1] for message in messages
    ] == [
        f"{index} из {len(messages)}]"
        for index in range(1, len(messages) + 1)
    ]
    assert [
        line
        for message in messages
        for line in message.split("\n\n", 1)[1]
        .split("\n[Часть ", 1)[0]
        .splitlines()
    ] == rows


def test_general_report_splits_a_single_oversized_row():
    message_parts = _split_general_report_messages(
        "Отчёт",
        "x" * 100,
        max_length=80,
    )

    assert len(message_parts) > 1
    assert all(len(message) <= 80 for message in message_parts)
    assert sum(
        len(message.split("\n\n", 1)[1].split("\n[Часть ", 1)[0])
        for message in message_parts
    ) == 100


def test_general_event_report_query_groups_historic_reports_by_sport():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with SyncSession(engine) as session:
        category = Category(title="Профи")
        running = Sport(title="Бег")
        swimming = Sport(title="Плавание")
        event = Event(
            title="Общее по категории",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 1, 31),
            event_type=EventType.DISTANCE,
        )
        event.event_categories = [
            EventCategory(
                category=category,
                sport=running,
                distance_km=Decimal("10.00"),
            ),
            EventCategory(
                category=category,
                sport=swimming,
                distance_km=Decimal("2.00"),
            ),
        ]
        user = User(vk_id=1, first_name="А", last_name="Участник")
        session.add_all([event, user])
        session.flush()
        user_id = user.id

        current_category = session.query(EventCategory).filter_by(
            sport_id=swimming.id
        ).one()
        registration = Registration(
            user_id=user.id,
            event_id=event.id,
            event_category_id=current_category.id,
            extra_points=5,
        )
        session.add(registration)
        session.flush()
        assert registration.extra_points == 5
        session.add_all(
            [
                Report(
                    registration_id=registration.id,
                    sport_id=running.id,
                    distance_km=Decimal("8.50"),
                    peer_id=1,
                    conversation_message_id=1,
                    created_at=datetime(2026, 1, 5, 10, tzinfo=timezone.utc),
                ),
                Report(
                    registration_id=registration.id,
                    sport_id=swimming.id,
                    distance_km=Decimal("1.25"),
                    peer_id=1,
                    conversation_message_id=2,
                    created_at=datetime(2026, 1, 6, 10, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

        rows = session.execute(
            _general_event_report_query(event.id, category.id)
        ).all()
        weekly_rows = session.execute(
            _general_report_weekly_rows_query(event.id, category.id)
        ).all()

    assert {
        row.sport_title: (
            row.training_count,
            row.total_distance,
            row.extra_points,
        )
        for row in rows
    } == {
        "Бег": (1, Decimal("8.50"), 5),
        "Плавание": (1, Decimal("1.25"), 5),
    }
    assert len(weekly_rows) == 2
    assert {row.user_id for row in weekly_rows} == {user_id}
    engine.dispose()


def test_event_is_registration_available_requires_open_not_finished_event():
    today = date(2026, 1, 10)

    assert event_is_registration_available(date(2026, 1, 12), date(2026, 1, 20), True, today)
    assert event_is_registration_available(date(2026, 1, 8), date(2026, 1, 20), True, today)
    assert not event_is_registration_available(date(2026, 1, 8), date(2026, 1, 20), True, date(2026, 1, 21))
    assert not event_is_registration_available(date(2026, 1, 12), date(2026, 1, 20), False, today)


def test_event_is_report_available_requires_started_event_regardless_of_registration():
    today = date(2026, 1, 10)

    assert event_is_report_available(date(2026, 1, 8), date(2026, 1, 20), True, today)
    assert event_is_report_available(date(2026, 1, 8), date(2026, 1, 20), False, today)
    assert not event_is_report_available(date(2026, 1, 12), date(2026, 1, 20), True, today)


@pytest.mark.asyncio
async def test_start_general_event_report_requires_admin(monkeypatch):
    class FakeMessage:
        def __init__(self):
            self.from_id = 123
            self.peer_id = self.from_id
            self.text = "/event_report"
            self.ctx_api = SimpleNamespace()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

    fake_message = FakeMessage()

    async def fake_get_or_create_user(*args, **kwargs):
        return SimpleNamespace(is_admin=False)

    monkeypatch.setattr("app.bot.handlers.stats.get_or_create_user", fake_get_or_create_user)

    await start_general_event_report(fake_message)

    assert fake_message.answers
    assert "только администраторам" in fake_message.answers[0][0]


def test_cancel_handler_matches_report_challenge_state():
    handler = cancel_labeler.message_view.handlers[0]
    state_rule = next(rule for rule in handler.rules if getattr(rule, "state", None) is not None)

    assert str(ReportState.WAITING_CHALLENGE) in state_rule.state


@pytest.mark.asyncio
async def test_get_vk_profile_uses_api_client_directly():
    class FakeUsersApi:
        async def get(self, **kwargs):
            assert kwargs == {"user_ids": 123, "fields": "first_name,last_name"}
            return [SimpleNamespace(first_name="Ada", last_name="Lovelace")]

    api = SimpleNamespace(users=FakeUsersApi())

    profile = await get_vk_profile(api, 123)

    assert profile == {
        "user_vk_id": 123,
        "first_name": "Ada",
        "last_name": "Lovelace",
    }


@pytest.mark.asyncio
async def test_get_or_create_user_refreshes_placeholder_profile(monkeypatch):
    user = SimpleNamespace(
        id=1,
        vk_id=123,
        first_name="Пользователь",
        last_name="123",
    )

    class FakeSession:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr("app.service.Session", lambda: session)

    async def fake_get_user_by_vk_id(session, vk_id):
        return user

    async def fake_get_vk_profile(api, vk_id):
        return {"user_vk_id": vk_id, "first_name": "Ada", "last_name": "Lovelace"}

    monkeypatch.setattr("app.service.get_user_by_vk_id", fake_get_user_by_vk_id)
    monkeypatch.setattr("app.service.get_vk_profile", fake_get_vk_profile)

    result = await get_or_create_user(SimpleNamespace(), 123)

    assert result is user
    assert (user.first_name, user.last_name) == ("Ada", "Lovelace")
    assert session.committed


@pytest.mark.asyncio
async def test_reg_creates_user_before_rejecting_group_chat(monkeypatch):
    class FakeMessage:
        def __init__(self):
            self.from_id = 123
            self.peer_id = 2_000_000_001
            self.ctx_api = SimpleNamespace()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append(text)

    fake_message = FakeMessage()
    created_users = []

    async def fake_get_or_create_user(*args, **kwargs):
        created_users.append(args[1])

    async def unexpected_registration_lookup(*args, **kwargs):
        raise AssertionError("group /reg must not proceed to registration lookup")

    monkeypatch.setattr(
        "app.bot.handlers.registration.get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(
        "app.bot.handlers.registration.render_registration_events",
        unexpected_registration_lookup,
    )

    await start_registration(fake_message)

    assert created_users == [fake_message.from_id]
    assert fake_message.answers
    assert "только в личных" in fake_message.answers[0]
