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


@event_management_labeler.message(text="/sport_change_open")
async def open_sport_change(message: Message):
    await _show_sport_change_events(message, sport_change_open=True)


@event_management_labeler.message(text="/sport_change_close")
async def close_sport_change(message: Message):
    await _show_sport_change_events(message, sport_change_open=False)


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


async def _show_sport_change_events(message: Message, sport_change_open: bool):
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("Failed to get user for sport change toggle")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    async with Session() as session:
        stmt = select(Event).where(
            Event.sport_change_open.is_(not sport_change_open),
        )
        if sport_change_open:
            stmt = stmt.where(Event.ends_on >= date.today())
        events = list(
            (
                await session.scalars(
                    stmt.order_by(Event.starts_on.asc(), Event.title.asc())
                )
            ).all()
        )

    if not events:
        await message.answer(
            "📭 Нет актуальных мероприятий, для которых можно "
            f"{'открыть' if sport_change_open else 'закрыть'} смену вида спорта."
        )
        return

    keyboard = Keyboard(inline=True)
    for event_record in events:
        label = f"{event_record.title[:25]} ({event_record.starts_on:%d.%m.%Y})"[:40]
        keyboard.add(
            Callback(
                label,
                payload={
                    "cmd": "toggle_sport_change",
                    "event_id": event_record.id,
                    "sport_change_open": sport_change_open,
                },
            )
        )
        keyboard.row()

    action = "открыть" if sport_change_open else "закрыть"
    await message.answer(
        f"Выбери мероприятие, для которого нужно {action} смену вида спорта:",
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
    command = payload.get("cmd")
    if command not in {"toggle_registration", "toggle_sport_change"}:
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
        target_open = (
            payload["registration_open"]
            if command == "toggle_registration"
            else payload["sport_change_open"]
        )
        if not isinstance(target_open, bool):
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
        if command == "toggle_registration":
            if target_open and event_record.ends_on < date.today():
                await event.show_snackbar(
                    "Нельзя открыть регистрацию на завершившееся мероприятие."
                )
                return
            if event_record.registration_open == target_open:
                status = "уже открыта" if target_open else "уже закрыта"
                await event.show_snackbar(f"Регистрация {status}.")
                return
            event_record.registration_open = target_open
            setting_name = "Регистрация"
        else:
            if target_open and event_record.ends_on < date.today():
                await event.show_snackbar(
                    "Нельзя открыть смену вида спорта для завершившегося мероприятия."
                )
                return
            if event_record.sport_change_open == target_open:
                status = "уже открыта" if target_open else "уже закрыта"
                await event.show_snackbar(f"Смена вида спорта {status}.")
                return
            event_record.sport_change_open = target_open
            setting_name = "Смена вида спорта"
        await session.commit()

    status = "открыта" if target_open else "закрыта"
    await event.send_message(
        f"✅ {setting_name} для мероприятия «{event_record.title}» {status}."
    )
