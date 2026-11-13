from datetime import date
from types import SimpleNamespace

import pytest

from app.bot.handlers.cancel import cancel_labeler
from app.bot.handlers.registration import start_registration
from app.bot.handlers.report import parse_report_distance
from app.bot.handlers.states import ReportState
from app.bot.handlers.stats import start_general_event_report
from app.service import get_or_create_user, get_vk_profile
from app.database.service import (
    event_is_registration_available,
    event_is_report_available,
)


def test_parse_report_distance_accepts_comma_and_dot():
    assert parse_report_distance("#отчет 10,5") == "10.50"
    assert parse_report_distance("#отчет 10.5") == "10.50"
    assert parse_report_distance("#отчет 10.50") == "10.50"


def test_parse_report_distance_rejects_invalid_format():
    try:
        parse_report_distance("#отчет 10.567")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for >2 decimal places")


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
        first_name="Неизвестный",
        last_name="Пользователь",
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
