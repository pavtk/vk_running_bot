from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from vkbottle.bot import Message
from vkbottle.tools.formatting import Formatter

from app.bot.handlers.states import (
    GeneralReportState,
    ParticipantsState,
    StatsState,
    state_dispenser,
)
from app.bot.labelers import stats_labeler
from app.database.models import (
    Category,
    Event,
    EventCategory,
    Registration,
    Report,
    Sport,
    User,
)
from app.database.service import Session, get_active_events
from app.service import get_or_create_user
from app.bot.handlers.stats_utils import group_reports_by_week
from app.settings import settings
from app.bot.state_storage import delete_user_state, get_user_state, set_user_state
from app.bot.utils import require_private_message
from app.time_utils import local_today
from app.logger import logger


MAX_REPORT_MESSAGE_LENGTH = 4000
SPORT_SCORE_FACTORS = {
    "бег": Decimal("1"),
    "велосипед": Decimal("0.5"),
    "лыжи": Decimal("0.8"),
    "скандинавская ходьба": Decimal("1.33"),
}


@stats_labeler.message(text="/participants")
async def start_event_participants_list(message: Message):
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("Failed to get user for participants list")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    try:
        async with Session() as session:
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .join(Registration, Registration.event_id == Event.id)
                        .distinct()
                        .order_by(Event.starts_on.desc(), Event.title.asc())
                    )
                ).unique().all()
            )
    except Exception:
        logger.exception("Failed to load events for participants list")
        await message.answer("❌ Не удалось загрузить список мероприятий.")
        return

    if not events:
        await message.answer("📭 Пока нет зарегистрированных участников.")
        return

    if len(events) == 1:
        await _send_event_participants(message, events[0].id)
        return

    lines = [
        f"{index}. {event.title}"
        for index, event in enumerate(events, 1)
    ]
    await state_dispenser.set(
        message.peer_id,
        ParticipantsState.WAITING_EVENT,
        event_ids=[event.id for event in events],
        user_id=user.id,
    )
    event_choices = _split_general_report_messages(
        "👥 Выбери мероприятие для списка участников:",
        "\n".join(lines),
    )
    for choice_part in event_choices:
        await message.answer(choice_part, disable_mentions=True)


@stats_labeler.message(state=ParticipantsState.WAITING_EVENT)
async def process_event_participants_choice(message: Message):
    state = await state_dispenser.get(message.peer_id)
    if state is None or not state.payload:
        await message.answer("⌛ Сессия истекла. Повторно введи /participants.")
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("Failed to verify admin for participants list")
        await message.answer("❌ Не удалось проверить права пользователя.")
        return

    if not user.is_admin or user.id != state.payload.get("user_id"):
        await state_dispenser.delete(message.peer_id)
        await message.answer("❌ Эта команда доступна только инициировавшему её администратору.")
        return

    event_ids = state.payload.get("event_ids") or []
    try:
        choice = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Введи номер мероприятия из списка, например: 1")
        return

    if choice < 1 or choice > len(event_ids):
        await message.answer(f"⚠️ Введи число от 1 до {len(event_ids)}.")
        return

    await _send_event_participants(message, event_ids[choice - 1])


def _format_event_participants(rows: list[tuple[str, str, str]]) -> str:
    if not rows:
        return "В этом мероприятии пока нет зарегистрированных участников."

    return "\n".join(
        f"{index}. {name}, {category}, {sport}"
        for index, (name, category, sport) in enumerate(rows, start=1)
    )


def _sort_general_report_categories(categories_by_id: dict[int, Category]):
    return sorted(categories_by_id.items(), key=lambda item: item[0])


async def _send_event_participants(message: Message, event_id: int):
    try:
        async with Session() as session:
            event = await session.get(Event, event_id)
            rows = (
                await session.execute(
                    _event_participants_query(event_id)
                )
            ).all()
    except Exception:
        logger.exception("Failed to load participants for event %s", event_id)
        await message.answer("❌ Не удалось загрузить участников мероприятия.")
        return

    if event is None:
        await message.answer("❌ Мероприятие не найдено.")
        return

    participant_rows = [
        (
            f"{first_name} {last_name}".strip(),
            category_title,
            sport_title,
        )
        for first_name, last_name, category_title, sport_title in rows
    ]
    report_body = _format_event_participants(participant_rows)
    header = f"👥 Участники мероприятия: {event.title}"
    await state_dispenser.delete(message.peer_id)
    for report_part in _split_general_report_messages(header, report_body):
        await message.answer(report_part, disable_mentions=True)


def _event_participants_query(event_id: int):
    return (
        select(
            User.first_name,
            User.last_name,
            Category.title,
            Sport.title,
        )
        .select_from(Registration)
        .join(User, User.id == Registration.user_id)
        .join(EventCategory, EventCategory.id == Registration.event_category_id)
        .join(Category, Category.id == EventCategory.category_id)
        .join(Sport, Sport.id == EventCategory.sport_id)
        .where(Registration.event_id == event_id)
        .order_by(
            EventCategory.category_id,
            Sport.title,
            User.last_name,
            User.first_name,
        )
    )


@stats_labeler.message(text="/event_report")
async def start_general_event_report(message: Message):
    """Сводный отчёт по мероприятию и категории с разбивкой по видам спорта."""
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    async with Session() as session:
        events = await get_active_events(session)

    if not events:
        await message.answer("📭 Сейчас нет активных событий для общего отчёта.")
        return

    if len(events) == 1:
        await _ask_category_for_general_report(message, events[0].id)
        return

    lines = [f"{i}. {event.title}" for i, event in enumerate(events, start=1)]
    await state_dispenser.set(
        message.peer_id,
        GeneralReportState.WAITING_EVENT,
        event_ids=[event.id for event in events],
    )
    await message.answer(
        "📊 Выбери мероприятие для общего отчёта:\n\n" + "\n".join(lines),
        disable_mentions=True,
    )


async def _ask_category_for_general_report(message: Message, event_id: int):
    async with Session() as session:
        event = await session.get(
            Event,
            event_id,
            options=[
                selectinload(Event.event_categories).selectinload(
                    EventCategory.category
                )
            ],
        )

    if event is None:
        await message.answer("❌ Событие не найдено.")
        return

    categories_by_id = {
        event_category.category_id: event_category.category
        for event_category in event.event_categories
    }
    categories = _sort_general_report_categories(categories_by_id)
    if not categories:
        await message.answer("📭 У этого события нет категорий для отчёта.")
        return

    if len(categories) == 1:
        await _render_general_event_report(message, event.id, categories[0][0])
        return

    lines = [f"{i}. {category.title}" for i, (_, category) in enumerate(categories, 1)]
    await state_dispenser.set(
        message.peer_id,
        GeneralReportState.WAITING_CATEGORY,
        event_id=event.id,
        category_ids=[category_id for category_id, _ in categories],
    )
    await message.answer(
        "📊 Выбери категорию для общего отчёта (все виды спорта):\n\n"
        + "\n".join(lines),
        disable_mentions=True,
    )


@stats_labeler.message(state=GeneralReportState.WAITING_EVENT)
async def process_general_event_choice(message: Message):
    state = await state_dispenser.get(message.peer_id)
    if state is None or not state.payload:
        await message.answer("⌛ Сессия истекла. Повторно введи /event_report.")
        return

    event_ids = state.payload.get("event_ids") or []
    raw_value = (message.text or "").strip()

    try:
        choice = int(raw_value)
    except ValueError:
        await message.answer("⚠️ Введи номер мероприятия из списка, например: 1")
        return

    if choice < 1 or choice > len(event_ids):
        await message.answer(f"⚠️ Введи число от 1 до {len(event_ids)}.")
        return

    await _ask_category_for_general_report(message, event_ids[choice - 1])


@stats_labeler.message(state=GeneralReportState.WAITING_CATEGORY)
async def process_general_category_choice(message: Message):
    state = await state_dispenser.get(message.peer_id)
    if state is None or not state.payload:
        await message.answer("⌛ Сессия истекла. Повторно введи /event_report.")
        return

    event_id = state.payload.get("event_id")
    category_ids = state.payload.get("category_ids") or []
    raw_value = (message.text or "").strip()

    try:
        choice = int(raw_value)
    except ValueError:
        await message.answer("⚠️ Введи номер категории из списка, например: 1")
        return

    if choice < 1 or choice > len(category_ids):
        await message.answer(f"⚠️ Введи число от 1 до {len(category_ids)}.")
        return

    await _render_general_event_report(message, event_id, category_ids[choice - 1])


def _aggregate_general_report_rows(
    rows: list[tuple[int, str, str | None, int, Decimal, int]],
) -> dict[int, dict]:
    participants: dict[int, dict] = {}
    for (
        user_id,
        name,
        sport_title,
        training_count,
        total_distance,
        extra_points,
    ) in rows:
        participant = participants.setdefault(
            user_id,
            {
                "name": name,
                "training_count": 0,
                "distance_by_sport": {},
                "extra_points": extra_points,
            },
        )
        participant["training_count"] += training_count
        if sport_title is None:
            continue

        participant["distance_by_sport"][sport_title] = total_distance

    return participants


def _format_general_report_table(participants: list[dict]) -> str:
    lines = []
    for index, participant in enumerate(participants, start=1):
        sports = ", ".join(
            f"{sport}: {distance:.2f} км"
            for sport, distance in sorted(
                participant["distance_by_sport"].items()
            )
        ) or "—"
        distance_score = _calculate_general_report_score(
            participant["distance_by_sport"]
        )
        norm_points = participant.get("weekly_norm_weeks", 0) * 3
        extra_points = participant.get("extra_points", 0)
        total_points = norm_points + extra_points
        lines.append(
            f"{index}. {participant['name']}, "
            f"{participant['training_count']} трен., {sports}, "
            f"{distance_score:.2f} условных км, "
            f"Балл. за норм.: {norm_points}, "
            f"Доп. Баллы: {extra_points}, "
            f"Всего баллов: {total_points}"
        )
    return "\n".join(lines)


def _count_fulfilled_weekly_norms(
    report_rows: list[tuple[int, datetime]],
    event_starts_on: date,
    through_date: date,
    runs_per_week: int | None,
    report_timezone: tzinfo,
) -> dict[int, int]:
    if not runs_per_week or runs_per_week <= 0 or through_date < event_starts_on:
        return {}

    reports_by_user: dict[int, list[tuple[datetime, Decimal]]] = {}
    for user_id, created_at in report_rows:
        reports_by_user.setdefault(user_id, []).append(
            (created_at, Decimal("0"))
        )

    fulfilled_norms = {}
    for user_id, reports in reports_by_user.items():
        fulfilled_norms[user_id] = sum(
            training_count >= runs_per_week
            for _, _, training_count in group_reports_by_week(
                reports,
                event_starts_on,
                through_date,
                report_timezone=report_timezone,
            )
        )
    return fulfilled_norms


def _calculate_general_report_score(
    distance_by_sport: dict[str, Decimal],
) -> Decimal:
    score = sum(
        (
            distance
            * SPORT_SCORE_FACTORS[sport.strip().casefold()]
            for sport, distance in distance_by_sport.items()
            if sport.strip().casefold() in SPORT_SCORE_FACTORS
        ),
        Decimal("0"),
    )
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _split_general_report_messages(
    header: str,
    report_body: str,
    max_length: int = MAX_REPORT_MESSAGE_LENGTH,
) -> list[str]:
    part_marker_reserve = len("\n[Часть 999999 из 999999]")
    body_limit = max_length - len(header) - 2 - part_marker_reserve
    if body_limit <= 0:
        raise ValueError("The report header exceeds the maximum message length.")

    lines = report_body.splitlines() or [""]
    body_parts: list[list[str]] = [[]]
    current_length = 0

    for line in lines:
        fragments = [
            line[index:index + body_limit]
            for index in range(0, len(line), body_limit)
        ] or [""]
        for fragment in fragments:
            added_length = len(fragment) + (1 if body_parts[-1] else 0)
            if body_parts[-1] and current_length + added_length > body_limit:
                body_parts.append([])
                current_length = 0
                added_length = len(fragment)
            body_parts[-1].append(fragment)
            current_length += added_length

    part_count = len(body_parts)
    messages = []
    for part_number, body_lines in enumerate(body_parts, start=1):
        body = "\n".join(body_lines)
        marker = f"\n[Часть {part_number} из {part_count}]"
        messages.append(f"{header}\n\n{body}{marker}")

    return messages


def _general_event_report_query(event_id: int, category_id: int):
    return (
        select(
            User.id.label("user_id"),
            User.first_name,
            User.last_name,
            Registration.extra_points.label("extra_points"),
            Sport.title.label("sport_title"),
            func.count(Report.id).label("training_count"),
            func.coalesce(func.sum(Report.distance_km), 0).label("total_distance"),
        )
        .select_from(Registration)
        .join(User, User.id == Registration.user_id)
        .join(EventCategory, EventCategory.id == Registration.event_category_id)
        .outerjoin(Report, Report.registration_id == Registration.id)
        .outerjoin(Sport, Sport.id == Report.sport_id)
        .where(
            Registration.event_id == event_id,
            EventCategory.category_id == category_id,
        )
        .group_by(
            User.id,
            User.first_name,
            User.last_name,
            Registration.extra_points,
            Sport.title,
        )
        .order_by(
            func.count(Report.id).desc(),
            func.coalesce(func.sum(Report.distance_km), 0).desc(),
            User.last_name.asc(),
            User.first_name.asc(),
        )
    )


def _general_report_weekly_rows_query(event_id: int, category_id: int):
    return (
        select(Registration.user_id, Report.created_at)
        .select_from(Registration)
        .join(EventCategory, EventCategory.id == Registration.event_category_id)
        .join(Report, Report.registration_id == Registration.id)
        .where(
            Registration.event_id == event_id,
            EventCategory.category_id == category_id,
        )
    )


async def _render_general_event_report(message: Message, event_id: int, category_id: int):
    async with Session() as session:
        event = await session.get(
            Event,
            event_id,
        )
        category = await session.get(Category, category_id)
        category_is_in_event = await session.scalar(
            select(EventCategory.id)
            .where(
                EventCategory.event_id == event_id,
                EventCategory.category_id == category_id,
            )
            .limit(1)
        )
        weekly_report_rows = (
            await session.execute(
                _general_report_weekly_rows_query(event_id, category_id)
            )
        ).all()

        rows = (
            await session.execute(
                _general_event_report_query(event_id, category_id)
            )
        ).all()

    if event is None or category is None or category_is_in_event is None:
        await message.answer("❌ Данные события или категории не найдены.")
        return

    event_starts_on = event.starts_on
    event_ends_on = event.ends_on
    runs_per_week = event.runs_per_week
    report_timezone = ZoneInfo(settings.TIMEZONE)
    fulfilled_weekly_norms = _count_fulfilled_weekly_norms(
        weekly_report_rows,
        event_starts_on,
        min(local_today(), event_ends_on),
        runs_per_week,
        report_timezone,
    )

    participants = _aggregate_general_report_rows(
        [
            (
                row.user_id,
                f"{row.first_name} {row.last_name}".strip(),
                row.sport_title,
                row.training_count or 0,
                row.total_distance or Decimal("0.00"),
                row.extra_points or 0,
            )
            for row in rows
        ]
    )
    for participant_id, participant in participants.items():
        fulfilled_weeks = fulfilled_weekly_norms.get(
            participant_id,
            0,
        )
        participant["weekly_norm_weeks"] = fulfilled_weeks

    ordered_participants = sorted(
        participants.values(),
        key=lambda item: (
            -item["training_count"],
            -sum(item["distance_by_sport"].values(), Decimal("0.00")),
            item["name"].casefold(),
        ),
    )
    if ordered_participants:
        report_table = _format_general_report_table(ordered_participants)
    else:
        report_table = "Участников нет."

    await state_dispenser.delete(message.peer_id)
    header = (
        f"📊 Общий отчёт по событию: {event.title}\n"
        f"Категория: {category.title} (все виды спорта)"
    )
    for report_part in _split_general_report_messages(header, report_table):
        await message.answer(report_part, disable_mentions=True)


@stats_labeler.message(text="/stats")
async def start_event_stats(message: Message):
    """Показывает статистику активного мероприятия или предлагает выбрать его."""
    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    async with Session() as session:
        stmt = (
            select(Registration)
            .options(selectinload(Registration.event))
            .join(Registration.event)
            .where(
                Registration.user_id == user.id,
                Event.starts_on <= local_today(),
                Event.ends_on >= local_today(),
            )
            .order_by(Registration.created_at.desc())
        )
        regs = list((await session.scalars(stmt)).all())

    if not regs:
        await message.answer("📭 Сейчас у тебя нет активных челленджей.")
        return

    if len(regs) == 1:
        await delete_user_state(message.peer_id, message.from_id)
        await send_event_stats(message, regs[0].id)
        return

    reg_ids = [reg.id for reg in regs]
    lines = []
    for i, reg in enumerate(regs, start=1):
        lines.append(f"{i}. {reg.event.title}")
    lines.append("\nНапиши номер пункта, например: 1")

    await set_user_state(
        message.peer_id,
        message.from_id,
        StatsState.WAITING_EVENT,
        registrations=reg_ids,
    )
    await message.answer(
        Formatter("📊 {:bold}\n\n{}").format("Выбери мероприятие:", "\n".join(lines))
    )


@stats_labeler.message(state=StatsState.WAITING_EVENT)
async def process_event_stats_choice(message: Message):
    """Обрабатывает выбор мероприятия по номеру в списке."""
    state = await get_user_state(message.peer_id, message.from_id)
    if state is None or not state.payload:
        await message.answer("⌛ Сессия истекла. Введи /stats снова.")
        return

    reg_ids = state.payload.get("registrations") or []
    raw_value = (message.text or "").strip()

    if raw_value.lower() in {"0", "отмена", "cancel"}:
        await delete_user_state(message.peer_id, message.from_id)
        await message.answer("❌ Выбор статистики отменён.")
        return

    try:
        choice = int(raw_value)
    except ValueError:
        await message.answer("⚠️ Введи номер мероприятия из списка, например: 1")
        return

    if choice < 1 or choice > len(reg_ids):
        await message.answer(f"⚠️ Введи число от 1 до {len(reg_ids)}.")
        return

    reg_id = reg_ids[choice - 1]
    await delete_user_state(message.peer_id, message.from_id)
    await send_event_stats(message, reg_id)


async def send_event_stats(message: Message, reg_id: int):
    async with Session() as session:
        reg = await session.get(
            Registration,
            reg_id,
            options=[selectinload(Registration.event)],
        )
        if reg is None:
            await message.answer("❌ Регистрация не найдена.")
            return

        event_title = reg.event.title
        event_starts_on = reg.event.starts_on
        event_ends_on = reg.event.ends_on
        runs_per_week = reg.event.runs_per_week
        rows = (
            await session.execute(
                select(Report.created_at, Report.distance_km)
                .where(Report.registration_id == reg.id)
                .order_by(Report.created_at.asc())
            )
        ).all()

    if not rows and (not runs_per_week or runs_per_week <= 0):
        await message.answer(
            f"📊 По мероприятию «{event_title}» пока нет отчётов."
        )
        return

    through_date = min(local_today(), event_ends_on)
    report_timezone = ZoneInfo(settings.TIMEZONE)
    weekly = group_reports_by_week(
        rows,
        event_starts_on,
        through_date,
        report_timezone=report_timezone,
    )
    lines = []
    for week_number, total, training_count in weekly:
        if training_count % 10 == 1 and training_count % 100 != 11:
            training_word = "тренировка"
        elif (
            training_count % 10 in {2, 3, 4}
            and training_count % 100 not in {12, 13, 14}
        ):
            training_word = "тренировки"
        else:
            training_word = "тренировок"
        line = (
            f"• {week_number} неделя: {training_count} {training_word}, "
            f"{total} км"
        )
        if runs_per_week and runs_per_week > 0:
            goal_status = (
                "выполнена"
                if training_count >= runs_per_week
                else "не выполнена"
            )
            line += f" (цель {training_count}/{runs_per_week}, {goal_status})"
        lines.append(line)

    await message.answer(Formatter("📊 {:bold}\n\n{}").format(event_title, "\n".join(lines)))
