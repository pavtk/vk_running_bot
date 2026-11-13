from app.database.models import Event, Registration, EventCategory
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from vkbottle.bot import Message, MessageEvent

from app.logger import logger
from app.service import get_or_create_user
from app.bot.labelers import registrations_show_labeler
from app.database.service import Session
from app.bot.utils import require_private_message


async def _send_my_registrations(message_or_event, user_id: int):
    """Формирует список регистраций пользователя и отправляет его в чат."""
    async with Session() as session:
        stmt = (
            select(Registration)
            .options(
                selectinload(Registration.event),
                selectinload(Registration.event_category).selectinload(EventCategory.category),
                selectinload(Registration.event_category).selectinload(EventCategory.sport),
            )
            .where(Registration.user_id == user_id)
            .order_by(Registration.id.desc())
        )
        regs = (await session.scalars(stmt)).all()

    if not regs:
        text = "📭 У тебя пока нет регистраций на мероприятия."
    else:
        lines = ["🎽 Твои регистрации:\n"]
        for reg in regs:
            if reg.event is None:
                continue

            starts = reg.event.starts_on.strftime("%d.%m.%Y") if reg.event.starts_on else "-"
            ends = reg.event.ends_on.strftime("%d.%m.%Y") if reg.event.ends_on else "-"
            category_title = (
                reg.event_category.category.title
                if reg.event_category is not None and reg.event_category.category is not None
                else "—"
            )
            sport_title = (
                reg.event_category.sport.title
                if reg.event_category is not None and reg.event_category.sport is not None
                else "—"
            )
            distance_text = (
                f" — {reg.event_category.distance_km} км"
                if reg.event_category is not None
                else ""
            )
            lines.append(
                f"🏁 {reg.event.title}\n"
                f"   🕒 {starts} — {ends}\n"
                f"   🏅 {sport_title}\n"
                f"   📌 {category_title}{distance_text}\n"
            )
        text = "\n".join(lines)

    if isinstance(message_or_event, MessageEvent):
        await message_or_event.send_message(text, disable_mentions=True)
    else:
        await message_or_event.answer(text, disable_mentions=True)


@registrations_show_labeler.message(text="/my_regs")
async def process_my_regs(message: Message):
    """Получает и отправляет список регистраций пользователя в личных сообщениях."""
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("get_or_create_user failed in process_my_regs")
        await message.answer("❌ Ошибка базы данных. Попробуй позже.", disable_mentions=True)
        return

    await _send_my_registrations(message, user.id)