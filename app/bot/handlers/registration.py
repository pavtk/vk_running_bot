import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from vkbottle import Callback, Keyboard, KeyboardButtonColor, GroupEventType
from vkbottle.bot import Message, MessageEvent

from app.bot.handlers.events_show import render_active_events
from app.bot.handlers.registration_toggle import handle_registration_toggle
from app.bot.handlers.states import RegistrationState, state_dispenser
from app.bot.labelers import registration_labeler
from app.service import get_or_create_user, render_registration_events
from app.database.service import Session
from app.database.models import Event, Registration, EventCategory
from app.logger import logger
from app.bot.utils import require_private_message

MAX_BUTTONS = 5  # Оставляем ряд под кнопку "Отмена"


@registration_labeler.message(text="/reg")
async def start_registration(message: Message):
    """Точка входа: показать активные мероприятия."""
    try:
        await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("get_or_create_user failed for /reg")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not await require_private_message(message):
        return

    if await state_dispenser.get(message.peer_id) is not None:
        await message.answer("⚠️ Уже идёт регистрация.\nПродолжи или отмени /cancel.")
        return

    events = await render_registration_events(registration_labeler, message.from_id)
    if not events:
        await message.answer("📭 Сейчас нет мероприятий с открытой регистрацией.")
        return

    await state_dispenser.set(message.peer_id, RegistrationState.WAITING_EVENT)

    lines = []
    for i, event in enumerate(events, 1):
        lines.append(f"{i}. {event['title']}")

    await message.answer(
        "👇 Выбери мероприятие для регистрации:",
        keyboard=_build_event_selection_keyboard(events),
    )


def _build_event_selection_keyboard(events: list[dict]) -> str:
    keyboard = Keyboard(inline=True)
    for event in events[:MAX_BUTTONS]:
        keyboard.add(
            Callback(
                event["title"][:40],
                payload={"cmd": "reg_event", "event_id": event["id"]},
            )
        )
        keyboard.row()
    keyboard.add(
        Callback("Отмена", payload={"cmd": "reg_cancel"}),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return keyboard.get_json()


def _parse_payload(raw_payload):
    """Поддерживает payload как dict, JSON-строку и пустое значение."""
    if raw_payload in (None, ""):
        return {}
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        try:
            parsed = json.loads(raw_payload)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@registration_labeler.raw_event(
    GroupEventType.MESSAGE_EVENT,
    dataclass=MessageEvent,
)
async def handle_registration_event(event: MessageEvent):
    """Единый обработчик нажатий на кнопки."""
    if event.peer_id != event.user_id:
        await event.show_snackbar("Эти действия доступны только в личных сообщениях боту.")
        return

    payload = _parse_payload(event.payload)
    cmd = payload.get("cmd")
    print(f"🔥 Событие получено! cmd={cmd}, payload={payload}")

    if cmd == "reg_event":
        await process_choose_category(event, payload)
    elif cmd == "reg_category":
        await process_confirm_registration(event, payload)
    elif cmd == "reg_back":
        await process_back_to_events(event)
    elif cmd == "reg_cancel":
        await process_cancel_registration(event)
    elif cmd == "my_regs":
        await show_my_registrations(event)
    elif cmd == "toggle_registration":
        await handle_registration_toggle(event)
    else:
        await event.show_snackbar("Неизвестное действие")


async def process_choose_category(event: MessageEvent, payload: dict | None = None):
    """Пользователь выбрал мероприятие — показываем категории."""
    payload = payload or _parse_payload(event.payload)
    event_id = payload.get("event_id")
    if event_id is None:
        await event.show_snackbar("❌ Не удалось определить мероприятие.")
        await state_dispenser.delete(event.peer_id)
        return

    try:
        event_id = int(event_id)
    except (TypeError, ValueError):
        await event.show_snackbar("❌ Некорректный идентификатор мероприятия.")
        await state_dispenser.delete(event.peer_id)
        return

    async with Session() as session:
        stmt = (
            select(Event)
            .options(
                selectinload(Event.event_categories).selectinload(EventCategory.category)
            )
            .where(Event.id == event_id)
        )
        event_obj = await session.scalar(stmt)
        
        if event_obj is None:
            await event.show_snackbar("❌ Мероприятие не найдено.")
            await state_dispenser.delete(event.peer_id)
            return
        
        categories = event_obj.event_categories
        event_title = event_obj.title

    if not categories:
        await event.show_snackbar("📭 У этого мероприятия нет категорий.")
        await state_dispenser.delete(event.peer_id)
        return

    # Сохраняем ID мероприятия в состоянии
    await state_dispenser.set(
        event.peer_id,
        RegistrationState.WAITING_CATEGORY,
        event_id=event_id,
    )

    keyboard = Keyboard(inline=True)
    for ec in categories[:MAX_BUTTONS]:
        label = ec.category.title
        if ec.distance_km is not None:
            label = f"{label} — {ec.distance_km} км"
        keyboard.add(
            Callback(
                label[:40],
                payload={"cmd": "reg_category", "event_category_id": ec.id},
            )
        )
        keyboard.row()
    keyboard.add(
        Callback("Назад", payload={"cmd": "reg_back"}),
    )
    keyboard.add(
        Callback("Отмена", payload={"cmd": "reg_cancel"}),
        color=KeyboardButtonColor.NEGATIVE,
    )

    await event.show_snackbar("Выбрано мероприятие")
    await event.send_message(
        f"🏁 {event_title}\n\n👇 Выбери категорию:",
        keyboard=keyboard.get_json(),
    )


async def process_back_to_events(event: MessageEvent):
    events = await render_registration_events(event.ctx_api, event.user_id)
    if not events:
        await state_dispenser.delete(event.peer_id)
        await event.send_message("📭 Сейчас нет мероприятий с открытой регистрацией.")
        return

    await state_dispenser.set(event.peer_id, RegistrationState.WAITING_EVENT)
    lines = [f"{i}. {item['title']}" for i, item in enumerate(events, start=1)]
    await event.send_message(
        "👇 Выбери мероприятие для регистрации:\n\n" + "\n".join(lines),
        keyboard=_build_event_selection_keyboard(events),
    )


async def process_confirm_registration(event: MessageEvent, payload: dict | None = None):
    """Пользователь выбрал категорию — пишем регистрацию."""
    state = await state_dispenser.get(event.peer_id)
    if state is None:
        await event.show_snackbar("⌛ Сессия истекла. Начни заново: /reg")
        return

    payload = payload or _parse_payload(event.payload)
    event_id = (state.payload or {}).get("event_id")
    event_category_id = payload.get("event_category_id")
    if event_id is None or event_category_id is None:
        await event.show_snackbar("❌ Некорректные данные. Начни заново: /reg")
        await state_dispenser.delete(event.peer_id)
        return

    try:
        event_id = int(event_id)
        event_category_id = int(event_category_id)
    except (TypeError, ValueError):
        await event.show_snackbar("❌ Некорректные данные. Начни заново: /reg")
        await state_dispenser.delete(event.peer_id)
        return

    # Получаем пользователя из БД (или создаем, если его нет)
    try:
        user = await get_or_create_user(event.ctx_api, event.user_id)
    except Exception:
        logger.exception("get_or_create_user failed in process_confirm_registration")
        await event.show_snackbar("❌ Ошибка базы данных. Попробуй позже.")
        return

    async with Session() as session:
        # Проверяем существующую регистрацию по внутреннему ID пользователя
        existing = await session.scalar(
            select(Registration).where(
                Registration.user_id == user.id,  # <-- используем user.id, а не event.user_id
                Registration.event_id == event_id,
            )
        )
        if existing is not None:
            await event.show_snackbar("✅ Ты уже зарегистрирован на это мероприятие.")
            await state_dispenser.delete(event.peer_id)
            return

        # Сохраняем регистрацию с внутренним ID пользователя
        new_reg = Registration(
            user_id=user.id,  # <-- используем user.id
            event_id=event_id,
            event_category_id=event_category_id,
        )
        session.add(new_reg)
        await session.commit()

    await state_dispenser.delete(event.peer_id)
    
    await event.send_message(
        "🎉 Ты успешно зарегистрирован!\n\nУвидимся на старте 🏃",
        keyboard=Keyboard(inline=True)
        .add(Callback("Назад к мероприятиям", payload={"cmd": "reg_back"}))
        .add(Callback("Мои регистрации", payload={"cmd": "my_regs"}))
        .get_json(),
    )

async def show_my_registrations(event: MessageEvent):
    """Показывает все регистрации пользователя: событие, даты и категорию."""
    try:
        user = await get_or_create_user(event.ctx_api, event.user_id)
    except Exception:
        logger.exception("get_or_create_user failed in show_my_registrations")
        await event.show_snackbar("❌ Ошибка базы данных. Попробуй позже.")
        return

    async with Session() as session:
        stmt = (
            select(Registration)
            .options(
                selectinload(Registration.event),
                selectinload(Registration.event_category).selectinload(EventCategory.category),
            )
            .where(Registration.user_id == user.id)
            .order_by(Registration.id.desc())
        )
        registrations = (await session.scalars(stmt)).all()

    if not registrations:
        await event.send_message("📭 У тебя пока нет регистраций на мероприятия.")
        return

    lines = ["🎽 Твои регистрации:\n"]
    for reg in registrations:
        if reg.event is None:
            continue

        starts = reg.event.starts_on.strftime("%d.%m.%Y") if reg.event.starts_on else "-"
        ends = reg.event.ends_on.strftime("%d.%m.%Y") if reg.event.ends_on else "-"
        category_title = (
            reg.event_category.category.title
            if reg.event_category is not None and reg.event_category.category is not None
            else "—"
        )
        lines.append(
            f"🏁 {reg.event.title}\n"
            f"   🕒 {starts} — {ends}\n"
            f"   📌 {category_title}\n"
        )

    await event.send_message("\n".join(lines), disable_mentions=True)


async def process_cancel_registration(event: MessageEvent):
    await state_dispenser.delete(event.peer_id)
    await event.show_snackbar("❌ Регистрация отменена.")