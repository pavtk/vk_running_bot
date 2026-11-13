import json
from datetime import date

from sqlalchemy import select
from vkbottle import Callback, Keyboard
from vkbottle.bot import BotLabeler, Message, MessageEvent

from app.bot.utils import require_private_message
from app.database.models import Event
from app.database.service import Session
from app.logger import logger
from app.service import get_or_create_user


event_management_labeler = BotLabeler()


@event_management_labeler.message(text="/open")
async def open_registration(message: Message):
    await _show_registration_events(message, registration_open=True)


@event_management_labeler.message(text="/close")
async def close_registration(message: Message):
    await _show_registration_events(message, registration_open=False)


async def _show_registration_events(message: Message, registration_open: bool):
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("Failed to get user for registration toggle")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    async with Session() as session:
        stmt = select(Event).where(Event.registration_open.is_(not registration_open))
        if registration_open:
            stmt = stmt.where(Event.ends_on >= date.today())
        stmt = stmt.order_by(Event.starts_on.asc(), Event.title.asc())
        events = list((await session.scalars(stmt)).all())

    if not events:
        text = (
            "📭 Нет мероприятий, для которых можно открыть регистрацию."
            if registration_open
            else "📭 Нет мероприятий с открытой регистрацией."
        )
        await message.answer(text)
        return

    keyboard = Keyboard(inline=True)
    for event in events:
        label = f"{event.title[:25]} ({event.starts_on:%d.%m.%Y})"[:40]
        keyboard.add(
            Callback(
                label,
                payload={
                    "cmd": "toggle_registration",
                    "event_id": event.id,
                    "registration_open": registration_open,
                },
            )
        )
        keyboard.row()

    verb = "открыть" if registration_open else "закрыть"
    await message.answer(
        f"Выбери мероприятие, для которого нужно {verb} регистрацию:",
        keyboard=keyboard.get_json(),
    )


def _parse_payload(raw_payload) -> dict:
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


async def handle_registration_toggle(event: MessageEvent):
    if event.peer_id != event.user_id:
        await event.show_snackbar("Управление регистрацией доступно только в личных сообщениях боту.")
        return

    payload = _parse_payload(event.payload)
    if payload.get("cmd") != "toggle_registration":
        return

    try:
        user = await get_or_create_user(event.ctx_api, event.user_id)
    except Exception:
        logger.exception("Failed to get user for registration toggle callback")
        await event.send_message("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await event.show_snackbar("Эта команда доступна только администраторам.")
        return

    try:
        event_id = int(payload["event_id"])
        registration_open = payload["registration_open"]
        if not isinstance(registration_open, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("Некорректные данные мероприятия.")
        return

    async with Session() as session:
        event_record = await session.scalar(
            select(Event)
            .where(Event.id == event_id)
            .with_for_update()
        )
        if event_record is None:
            await event.show_snackbar("Мероприятие не найдено.")
            return
        if registration_open and event_record.ends_on < date.today():
            await event.show_snackbar("Нельзя открыть регистрацию на завершившееся мероприятие.")
            return
        if event_record.registration_open == registration_open:
            status = "уже открыта" if registration_open else "уже закрыта"
            await event.show_snackbar(f"Регистрация {status}.")
            return

        event_record.registration_open = registration_open
        await session.commit()

    status = "открыта" if registration_open else "закрыта"
    await event.send_message(
        f"✅ Регистрация на мероприятие «{event_record.title}» {status}."
    )
