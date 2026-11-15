from sqlalchemy import select
from vkbottle.bot import Message

from app.bot.handlers.states import ExtraPointsState
from app.bot.labelers import extra_points_labeler
from app.bot.state_storage import (
    delete_user_state,
    get_user_state,
    set_user_state,
)
from app.bot.utils import require_private_message
from app.database.models import Event, Registration, User
from app.database.service import Session
from app.logger import logger
from app.service import get_or_create_user


MAX_EXTRA_POINTS = 2_147_483_647


def _extra_points_events_query():
    return (
        select(Event.id, Event.title, Event.starts_on)
        .join(Registration, Registration.event_id == Event.id)
        .distinct()
        .order_by(Event.starts_on.desc(), Event.title.asc())
    )


def _extra_points_registrations_query(event_id: int):
    return (
        select(
            Registration.id,
            User.first_name,
            User.last_name,
            Registration.extra_points,
        )
        .join(User, User.id == Registration.user_id)
        .where(Registration.event_id == event_id)
        .order_by(User.last_name, User.first_name, Registration.id)
    )


def _parse_positive_integer(raw_value: str | None) -> int | None:
    value = (raw_value or "").strip()
    if not value.isdecimal() or len(value) > 10:
        return None
    amount = int(value)
    if amount <= 0:
        return None
    return amount


def _parse_choice_numbers(
    raw_value: str | None,
    max_choice: int,
) -> list[int] | None:
    value = (raw_value or "").strip()
    if not value:
        return None

    choices: list[int] = []
    for part in value.split(","):
        choice = _parse_positive_integer(part)
        if choice is None or choice > max_choice or choice in choices:
            return None
        choices.append(choice)
    return choices


def _format_choices(rows: list[tuple], title: str) -> list[str]:
    lines = [f"{index}. {row[1]}" for index, row in enumerate(rows, start=1)]
    if not lines:
        return []

    max_length = 3500
    chunks: list[str] = []
    current_lines = [title]
    current_length = len(title)
    for line in lines:
        if current_length + len(line) + 1 > max_length and len(current_lines) > 1:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_length = 0
        current_lines.append(line)
        current_length += len(line) + 1
    chunks.append("\n".join(current_lines))
    return chunks


async def _verify_admin(message: Message, expected_user_id: int | None = None):
    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("Failed to verify admin for /extra_points")
        await message.answer("❌ Не удалось проверить права пользователя.")
        return None

    if not user.is_admin or (
        expected_user_id is not None and user.id != expected_user_id
    ):
        await message.answer("❌ Эта команда доступна только инициировавшему её администратору.")
        return None
    return user


async def _load_flow_state(message: Message, expected_state):
    state = await get_user_state(message.peer_id, message.from_id)
    if state is None or state.state != str(expected_state) or not state.payload:
        await delete_user_state(message.peer_id, message.from_id)
        await message.answer("⌛ Сессия истекла. Повторно введи /extra_points.")
        return None

    user = await _verify_admin(message, state.payload.get("admin_id"))
    if user is None:
        await delete_user_state(message.peer_id, message.from_id)
        return None
    return state


@extra_points_labeler.message(text="/extra_points")
async def start_extra_points_flow(message: Message):
    if not await require_private_message(message):
        return

    user = await _verify_admin(message)
    if user is None:
        return

    if await get_user_state(message.peer_id, message.from_id) is not None:
        await message.answer(
            "⚠️ Уже идёт другой сценарий. Продолжи его или отмени командой /cancel."
        )
        return

    try:
        async with Session() as session:
            events = (await session.execute(_extra_points_events_query())).all()
    except Exception:
        logger.exception("Failed to load events for /extra_points")
        await message.answer("❌ Не удалось загрузить список мероприятий.")
        return

    if not events:
        await message.answer("📭 Нет мероприятий с зарегистрированными участниками.")
        return

    await set_user_state(
        message.peer_id,
        message.from_id,
        ExtraPointsState.WAITING_EVENT,
        admin_id=user.id,
        event_ids=[row.id for row in events],
        event_titles=[row.title for row in events],
    )
    for chunk in _format_choices(
        [(row.id, row.title) for row in events],
        "🎯 Выбери мероприятие:",
    ):
        await message.answer(chunk, disable_mentions=True)


@extra_points_labeler.message(state=ExtraPointsState.WAITING_EVENT)
async def process_extra_points_event_choice(message: Message):
    state = await _load_flow_state(message, ExtraPointsState.WAITING_EVENT)
    if state is None:
        return

    choice = _parse_positive_integer(message.text)
    event_ids = state.payload.get("event_ids") or []
    if choice is None or choice > len(event_ids):
        await message.answer(f"⚠️ Введи номер мероприятия от 1 до {len(event_ids)}.")
        return

    event_id = event_ids[choice - 1]
    try:
        async with Session() as session:
            registrations = (
                await session.execute(_extra_points_registrations_query(event_id))
            ).all()
    except Exception:
        logger.exception("Failed to load registrations for event %s", event_id)
        await message.answer("❌ Не удалось загрузить участников мероприятия.")
        return

    if not registrations:
        await delete_user_state(message.peer_id, message.from_id)
        await message.answer("📭 В этом мероприятии нет зарегистрированных участников.")
        return

    participant_rows = [
        (
            row.id,
            f"{row.first_name} {row.last_name}".strip(),
            row.extra_points,
        )
        for row in registrations
    ]
    await set_user_state(
        message.peer_id,
        message.from_id,
        ExtraPointsState.WAITING_PARTICIPANT,
        admin_id=state.payload["admin_id"],
        event_id=event_id,
        registration_ids=[row[0] for row in participant_rows],
        participant_names=[row[1] for row in participant_rows],
    )
    options = [
        (registration_id, f"{name} — сейчас {points} экстра-баллов")
        for (registration_id, name, points) in participant_rows
    ]
    for chunk in _format_choices(
        options,
        "👤 Выбери одного или нескольких участников (номера через запятую, "
        "например: 1, 2):",
    ):
        await message.answer(chunk, disable_mentions=True)


@extra_points_labeler.message(state=ExtraPointsState.WAITING_PARTICIPANT)
async def process_extra_points_participant_choice(message: Message):
    state = await _load_flow_state(message, ExtraPointsState.WAITING_PARTICIPANT)
    if state is None:
        return

    registration_ids = state.payload.get("registration_ids") or []
    participant_names = state.payload.get("participant_names") or []
    choices = _parse_choice_numbers(message.text, len(registration_ids))
    if choices is None:
        await message.answer(
            "⚠️ Введи уникальные номера участников через запятую от 1 до "
            f"{len(registration_ids)}, например: 1, 2."
        )
        return

    selected_registration_ids = [registration_ids[index - 1] for index in choices]
    selected_participant_names = [participant_names[index - 1] for index in choices]
    await set_user_state(
        message.peer_id,
        message.from_id,
        ExtraPointsState.WAITING_POINTS,
        admin_id=state.payload["admin_id"],
        event_id=state.payload["event_id"],
        registration_ids=selected_registration_ids,
        participant_names=selected_participant_names,
    )
    await message.answer(
        "Введи количество экстра-баллов для каждого выбранного участника "
        "(целое положительное число):",
        disable_mentions=True,
    )


@extra_points_labeler.message(state=ExtraPointsState.WAITING_POINTS)
async def process_extra_points_amount(message: Message):
    state = await _load_flow_state(message, ExtraPointsState.WAITING_POINTS)
    if state is None:
        return

    amount = _parse_positive_integer(message.text)
    if amount is None:
        await message.answer("⚠️ Введи целое число баллов больше нуля.")
        return

    try:
        async with Session() as session:
            registrations = (
                await session.scalars(
                    select(Registration).where(
                        Registration.id.in_(state.payload["registration_ids"]),
                        Registration.event_id == state.payload["event_id"],
                    ).with_for_update()
                )
            ).all()
            if len(registrations) != len(state.payload["registration_ids"]):
                await delete_user_state(message.peer_id, message.from_id)
                await message.answer(
                    "❌ Одна или несколько регистраций не найдены. "
                    "Запусти команду /extra_points заново."
                )
                return

            registrations_by_id = {
                registration.id: registration for registration in registrations
            }
            selected_registration_ids = state.payload["registration_ids"]
            updated_points = [
                registrations_by_id[registration_id].extra_points + amount
                for registration_id in selected_registration_ids
            ]
            if any(points > MAX_EXTRA_POINTS for points in updated_points):
                await message.answer(
                    f"⚠️ Итоговое значение не должно превышать {MAX_EXTRA_POINTS}."
                )
                return

            for registration_id, points in zip(
                selected_registration_ids,
                updated_points,
            ):
                registrations_by_id[registration_id].extra_points = points
            await session.commit()
    except Exception:
        logger.exception("Failed to add extra points to registration")
        await message.answer("❌ Не удалось начислить баллы. Попробуй позже.")
        return

    await delete_user_state(message.peer_id, message.from_id)
    confirmation_rows = [
        (
            registration_id,
            f"{name} — теперь {points} экстра-баллов",
        )
        for registration_id, name, points in zip(
            state.payload["registration_ids"],
            state.payload["participant_names"],
            updated_points,
        )
    ]
    for chunk in _format_choices(
        confirmation_rows,
        f"✅ Начислено по {amount} экстра-баллов "
        f"{len(confirmation_rows)} участникам:",
    ):
        await message.answer(chunk, disable_mentions=True)
