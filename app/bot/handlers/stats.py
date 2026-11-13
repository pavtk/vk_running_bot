from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from vkbottle.bot import Message
from vkbottle.tools.formatting import Formatter

from app.bot.handlers.states import GeneralReportState, StatsState, state_dispenser
from app.bot.labelers import stats_labeler
from app.database.models import Category, Event, EventCategory, Registration, Report, User
from app.database.service import Session, get_active_events
from app.service import get_or_create_user
from app.bot.handlers.stats_utils import group_reports_by_week
from app.settings import settings
from app.bot.state_storage import delete_user_state, get_user_state, set_user_state
from app.bot.utils import require_private_message


@stats_labeler.message(text="/event_report")
async def start_general_event_report(message: Message):
    """Сводный отчёт по участникам выбранного активного мероприятия и категории."""
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
            options=[selectinload(Event.event_categories).selectinload(EventCategory.category)],
        )

    if event is None:
        await message.answer("❌ Событие не найдено.")
        return

    categories = event.event_categories
    if not categories:
        await message.answer("📭 У этого события нет категорий для отчёта.")
        return

    if len(categories) == 1:
        await _render_general_event_report(message, event.id, categories[0].id)
        return

    lines = [f"{i}. {ec.category.title}" for i, ec in enumerate(categories, start=1)]
    await state_dispenser.set(
        message.peer_id,
        GeneralReportState.WAITING_CATEGORY,
        event_id=event.id,
        category_ids=[ec.id for ec in categories],
    )
    await message.answer(
        "📊 Выбери категорию для общего отчёта:\n\n" + "\n".join(lines),
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


async def _render_general_event_report(message: Message, event_id: int, category_id: int):
    async with Session() as session:
        event = await session.get(
            Event,
            event_id,
            options=[selectinload(Event.event_categories).selectinload(EventCategory.category)],
        )
        category = await session.get(
            EventCategory,
            category_id,
            options=[selectinload(EventCategory.category)],
        )

        stmt = (
            select(
                User.first_name,
                User.last_name,
                Category.title.label("category_title"),
                func.count(Report.id).label("training_count"),
                func.coalesce(func.sum(Report.distance_km), 0).label("total_distance"),
            )
            .select_from(Registration)
            .join(User, User.id == Registration.user_id)
            .join(EventCategory, EventCategory.id == Registration.event_category_id)
            .join(Category, Category.id == EventCategory.category_id)
            .outerjoin(Report, Report.registration_id == Registration.id)
            .where(
                Registration.event_id == event_id,
                Registration.event_category_id == category_id,
            )
            .group_by(User.id, User.first_name, User.last_name, Category.title)
            .order_by(
                func.count(Report.id).desc(),
                func.coalesce(func.sum(Report.distance_km), 0).desc(),
                User.last_name.asc(),
                User.first_name.asc(),
            )
        )
        rows = (await session.execute(stmt)).all()

    if event is None or category is None:
        await message.answer("❌ Данные события или категории не найдены.")
        return

    if not rows:
        await message.answer(
            f"📊 Общий отчёт по событию: {event.title}\nКатегория: {category.category.title}\n\nУчастников нет.",
            disable_mentions=True,
        )
        return

    lines = []
    for i, row in enumerate(rows, start=1):
        full_name = f"{row.first_name} {row.last_name}".strip()
        training_count = row.training_count or 0
        total_distance = row.total_distance or Decimal("0.00")
        lines.append(
            f"{i}. {full_name} — {row.category_title} — {training_count} трен. — {float(total_distance):.2f} км"
        )

    await state_dispenser.delete(message.peer_id)
    await message.answer(
        f"📊 Общий отчёт по событию: {event.title}\nКатегория: {category.category.title}\n\n" + "\n".join(lines),
        disable_mentions=True,
    )


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
                Event.starts_on <= date.today(),
                Event.ends_on >= date.today(),
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

    report_timezone = ZoneInfo(settings.TIMEZONE)
    through_date = min(datetime.now(report_timezone).date(), event_ends_on)
    weekly = group_reports_by_week(
        rows,
        event_starts_on,
        through_date,
        report_timezone=report_timezone,
    )
    lines = []
    for week_number, total, run_count in weekly:
        if run_count % 10 == 1 and run_count % 100 != 11:
            run_word = "пробежка"
        elif run_count % 10 in {2, 3, 4} and run_count % 100 not in {12, 13, 14}:
            run_word = "пробежки"
        else:
            run_word = "пробежек"
        line = f"• {week_number} неделя: {run_count} {run_word}, {total} км"
        if runs_per_week and runs_per_week > 0:
            goal_status = "выполнена" if run_count >= runs_per_week else "не выполнена"
            line += f" (цель {run_count}/{runs_per_week}, {goal_status})"
        lines.append(line)

    await message.answer(Formatter("📊 {:bold}\n\n{}").format(event_title, "\n".join(lines)))
