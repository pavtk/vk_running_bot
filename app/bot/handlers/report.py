import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from vkbottle.bot import Message
from vkbottle.dispatch.rules.base import RegexRule

from app.bot.handlers.states import ReportState
from app.bot.labelers import report_labeler
from app.bot.state_storage import delete_user_state, get_user_state, set_user_state
from app.database.models import Event, Registration, Report, EventCategory
from app.database.service import Session
from app.service import get_or_create_user


async def validate_report_distance_for_registration(
    registration_id: int,
    distance_km: Decimal,
) -> tuple[bool, str | None]:
    """Проверяет, что дистанция отчёта не меньше минимума выбранной категории."""
    async with Session() as session:
        registration = await session.get(
            Registration,
            registration_id,
            options=[selectinload(Registration.event_category)],
        )
        if registration is None or registration.event_category is None:
            return True, None

        minimum_km = registration.event_category.distance_km
        if distance_km < minimum_km:
            return False, (
                f"⚠️ Для этой категории минимальная дистанция — {minimum_km} км. "
                f"Ты отправил {distance_km} км."
            )

        return True, None


def parse_report_distance(raw_text: str) -> str:
    """Парсит дистанцию из текста вида '#отчет 10,5' и возвращает строку '10.50'."""
    if raw_text is None:
        raise ValueError("Текст отчёта пустой.")

    text = raw_text.strip()
    if not text:
        raise ValueError("Текст отчёта пустой.")

    match = re.search(r"#\s*отчет\b\s*(.*)", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError("В сообщении должен быть тег #отчет.")

    tail = match.group(1).strip()
    if not tail:
        raise ValueError("После #отчет укажи дистанцию в км, например: #отчет 10,5")

    number_match = re.search(r"\d+(?:[.,]\d+)?", tail)
    if not number_match:
        raise ValueError("После #отчет укажи дистанцию в км, например: #отчет 10,5")

    candidate = number_match.group(0).replace(",", ".")
    try:
        distance = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError("Некорректный формат расстояния. Используй число вида 10,5 или 10.5") from exc

    if distance <= 0:
        raise ValueError("Дистанция должна быть больше нуля.")

    if len(candidate.split(".")[-1]) > 2:
        raise ValueError("Расстояние должно быть не больше 2 знаков после запятой.")

    return format(distance.quantize(Decimal("0.01")), ".2f")


async def save_report_for_registration(
    registration_id: int,
    distance_km: Decimal,
    peer_id: int,
    conversation_message_id: int,
    comment: str | None = None,
):
    async with Session() as session:
        report = Report(
            registration_id=registration_id,
            comment=comment,
            distance_km=distance_km,
            peer_id=peer_id,
            conversation_message_id=conversation_message_id,
        )
        session.add(report)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
        return True


async def get_all_registrations_for_user(user_id: int) -> list[Registration]:
    async with Session() as session:
        stmt = (
            select(Registration)
            .options(selectinload(Registration.event))
            .join(Registration.event)
            .where(Registration.user_id == user_id)
            .order_by(Registration.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())


async def get_reportable_registrations_for_user(user_id: int) -> list[Registration]:
    async with Session() as session:
        stmt = (
            select(Registration)
            .options(selectinload(Registration.event))
            .join(Registration.event)
            .where(
                Registration.user_id == user_id,
                Event.starts_on <= date.today(),
                Event.ends_on >= date.today(),
            )
            .order_by(Registration.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())


async def get_active_registrations_for_user(user_id: int) -> list[Registration]:
    return await get_reportable_registrations_for_user(user_id)


@report_labeler.message(RegexRule(r"(?i).*#\s*отчет.*"))
async def handle_report(message: Message):
    """Обрабатывает отчёт с фото и расстоянием. Если пользователь активен в нескольких челленджах, просит выбрать один."""
    photo_attachments = message.get_photo_attachments() or []
    if not photo_attachments:
        await message.answer(
            "📷 Для отчёта нужно прикрепить фото. Пример: #отчет 10,5",
            disable_mentions=True,
        )
        return

    text = (message.text or "").strip()
    try:
        distance_km = parse_report_distance(text)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}\nПример: #отчет 10,5", disable_mentions=True)
        return

    comment = re.sub(r"#\s*отчет\b", "", text, flags=re.IGNORECASE).strip() or None

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    all_regs = await get_all_registrations_for_user(user.id)
    active_regs = await get_reportable_registrations_for_user(user.id)

    if not all_regs:
        await message.answer(
            "❌ Сначала зарегистрируйся на активный челлендж через /reg.",
            disable_mentions=True,
        )
        return

    if not active_regs:
        await message.answer(
            "⚠️ Ты зарегестрирован, но активный челлендж ещё не начался или уже завершился. "
            "Выбери актуальный челлендж через /reg.",
            disable_mentions=True,
        )
        return

    if len(active_regs) == 1:
        reg = active_regs[0]
        allowed, validation_error = await validate_report_distance_for_registration(
            reg.id,
            Decimal(distance_km),
        )
        if not allowed:
            await message.answer(validation_error, disable_mentions=True)
            return

        saved = await save_report_for_registration(
            registration_id=reg.id,
            distance_km=Decimal(distance_km),
            peer_id=message.peer_id,
            conversation_message_id=message.conversation_message_id,
            comment=comment,
        )
        if not saved:
            await message.answer("⚠️ Отчёт из этого сообщения уже сохранён.", disable_mentions=True)
            return
        await message.answer(f"✅ Отчёт сохранён: {distance_km} км", disable_mentions=True)
        return

    lines = []
    for i, reg in enumerate(active_regs, start=1):
        lines.append(f"{i}. {reg.event.title}")
    lines.append("\nНапиши номер пункта, например: 1")

    await set_user_state(
        message.peer_id,
        message.from_id,
        ReportState.WAITING_CHALLENGE,
        registrations=[reg.id for reg in active_regs],
        distance_km=distance_km,
        comment=comment,
    )
    text = "📊 Выбери, в какой челлендж сдавать отчёт:\n\n" + "\n".join(lines)
    await message.answer(text, disable_mentions=True)


@report_labeler.message(state=ReportState.WAITING_CHALLENGE)
async def handle_report_challenge_choice(message: Message):
    """Выбирает активный challenge для отчёта после команды #отчет."""
    state = await get_user_state(message.peer_id, message.from_id)
    if state is None or not state.payload:
        await message.answer("⌛ Сессия истекла. Повторно отправь #отчет.")
        return

    reg_ids = state.payload.get("registrations") or []
    raw_value = (message.text or "").strip()

    if raw_value.lower() in {"0", "отмена", "cancel"}:
        await delete_user_state(message.peer_id, message.from_id)
        await message.answer("❌ Выбор отменён.")
        return

    try:
        choice = int(raw_value)
    except ValueError:
        await message.answer("⚠️ Введи номер челленджа из списка, например: 1")
        return

    if choice < 1 or choice > len(reg_ids):
        await message.answer(f"⚠️ Введи число от 1 до {len(reg_ids)}.")
        return

    reg_id = reg_ids[choice - 1]
    pending_distance = state.payload.get("distance_km")
    pending_comment = state.payload.get("comment")
    if pending_distance is None:
        await delete_user_state(message.peer_id, message.from_id)
        await message.answer("❌ Данные отчёта потерялись. Повтори #отчет.")
        return

    allowed, validation_error = await validate_report_distance_for_registration(
        reg_id,
        Decimal(pending_distance),
    )
    await delete_user_state(message.peer_id, message.from_id)
    if not allowed:
        await message.answer(validation_error, disable_mentions=True)
        return

    saved = await save_report_for_registration(
        registration_id=reg_id,
        distance_km=Decimal(pending_distance),
        peer_id=message.peer_id,
        conversation_message_id=message.conversation_message_id,
        comment=pending_comment,
    )

    if not saved:
        await message.answer("⚠️ Этот отчёт уже сохранён.", disable_mentions=True)
        return

    await message.answer(
        f"✅ Отчёт сохранён: {pending_distance} км",
        disable_mentions=True,
    )
