import json
from datetime import date

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
from app.database.models import (
    Category,
    Event,
    Registration,
    EventCategory,
)
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
    elif cmd == "reg_sport":
        await process_choose_sport(event, payload)
    elif cmd == "reg_sport_page":
        await process_choose_sport_page(event, payload)
    elif cmd == "reg_sports_back":
        await process_back_to_sports(event, payload)
    elif cmd == "reg_category_page":
        await process_choose_category_page(event, payload)
    elif cmd == "reg_category":
        await process_confirm_registration(event, payload)
    elif cmd == "change_sport_registration":
        await process_change_sport_registration(event, payload)
    elif cmd == "change_sport_targets_page":
        await process_change_sport_targets_page(event, payload)
    elif cmd == "confirm_sport_change":
        await process_confirm_sport_change(event, payload)
    elif cmd == "reg_back":
        await process_back_to_events(event)
    elif cmd == "reg_cancel":
        await process_cancel_registration(event)
    elif cmd == "my_regs":
        await show_my_registrations(event)
    elif cmd in {"toggle_registration", "toggle_sport_change"}:
        await handle_registration_toggle(event)
    elif cmd == "change_sport_cancel":
        await event.show_snackbar("Смена вида спорта отменена.")
    else:
        await event.show_snackbar("Неизвестное действие")


async def process_choose_category(event: MessageEvent, payload: dict | None = None):
    """Пользователь выбрал мероприятие — показываем виды спорта."""
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

    await _send_sport_page(event, event_id, page=0, initial=True)


async def _load_event_categories(event_id: int) -> tuple[str | None, list[dict]]:
    async with Session() as session:
        stmt = (
            select(Event)
            .options(
                selectinload(Event.event_categories).selectinload(
                    EventCategory.category
                ),
                selectinload(Event.event_categories).selectinload(
                    EventCategory.sport
                ),
            )
            .where(Event.id == event_id)
        )
        event_obj = await session.scalar(stmt)
        if event_obj is None:
            return None, []

        return event_obj.title, [
            {
                "event_category_id": item.id,
                "sport_id": item.sport_id,
                "sport_title": item.sport.title,
                "category_title": item.category.title,
                "distance_km": item.distance_km,
            }
            for item in event_obj.event_categories
        ]


def _sports_from_categories(categories: list[dict]) -> list[dict]:
    sports_by_id = {
        item["sport_id"]: {
            "id": item["sport_id"],
            "title": item["sport_title"],
        }
        for item in categories
    }
    return sorted(sports_by_id.values(), key=lambda item: item["title"].casefold())


def _categories_for_sport(
    categories: list[dict],
    sport_id: int,
) -> list[dict]:
    return sorted(
        (item for item in categories if item["sport_id"] == sport_id),
        key=lambda item: item["category_title"].casefold(),
    )


async def _send_sport_page(
    event: MessageEvent,
    event_id: int,
    page: int,
    initial: bool = False,
):
    try:
        event_title, categories = await _load_event_categories(event_id)
    except Exception:
        logger.exception("Failed to load sports for registration")
        await event.show_snackbar("❌ Не удалось загрузить виды спорта.")
        return

    if event_title is None:
        await event.show_snackbar("❌ Мероприятие не найдено.")
        await state_dispenser.delete(event.peer_id)
        return

    sports = _sports_from_categories(categories)
    if not sports:
        await event.show_snackbar("📭 У этого мероприятия нет доступных видов спорта.")
        await state_dispenser.delete(event.peer_id)
        return

    last_page = (len(sports) - 1) // MAX_BUTTONS
    if page < 0 or page > last_page:
        await event.show_snackbar("❌ Такой страницы нет.")
        return

    await state_dispenser.set(
        event.peer_id,
        RegistrationState.WAITING_SPORT,
        event_id=event_id,
        page=page,
    )
    keyboard = Keyboard(inline=True)
    start = page * MAX_BUTTONS
    for sport in sports[start:start + MAX_BUTTONS]:
        keyboard.add(
            Callback(
                sport["title"][:40],
                payload={
                    "cmd": "reg_sport",
                    "event_id": event_id,
                    "sport_id": sport["id"],
                },
            )
        )
        keyboard.row()

    if page > 0:
        keyboard.add(
            Callback(
                "← Назад",
                payload={
                    "cmd": "reg_sport_page",
                    "event_id": event_id,
                    "page": page - 1,
                },
            )
        )
    if page < last_page:
        keyboard.add(
            Callback(
                "Далее →",
                payload={
                    "cmd": "reg_sport_page",
                    "event_id": event_id,
                    "page": page + 1,
                },
            )
        )
    if page > 0 or page < last_page:
        keyboard.row()
    keyboard.add(
        Callback("К мероприятиям", payload={"cmd": "reg_back"}),
    )
    keyboard.row()
    keyboard.add(
        Callback("Отмена", payload={"cmd": "change_sport_cancel"}),
        color=KeyboardButtonColor.NEGATIVE,
    )

    page_text = f"Страница {page + 1}/{last_page + 1}\n\n" if last_page > 0 else ""
    await event.show_snackbar("Выбрано мероприятие" if initial else "Страница открыта")
    await event.send_message(
        f"🏁 {event_title}\n\n{page_text}👇 Сначала выбери вид спорта:",
        keyboard=keyboard.get_json(),
    )


async def process_choose_sport(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        event_id = int(payload["event_id"])
        sport_id = int(payload["sport_id"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректные данные вида спорта.")
        return

    state = await state_dispenser.get(event.peer_id)
    if (
        state is None
        or state.state != str(RegistrationState.WAITING_SPORT)
        or (state.payload or {}).get("event_id") != event_id
    ):
        await event.show_snackbar("⌛ Сессия выбора истекла. Начни заново: /reg")
        return

    await _send_category_page(event, event_id, sport_id, page=0, initial=True)


async def process_choose_sport_page(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        event_id = int(payload["event_id"])
        page = int(payload["page"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректная страница выбора.")
        return

    state = await state_dispenser.get(event.peer_id)
    if (
        state is None
        or state.state != str(RegistrationState.WAITING_SPORT)
        or (state.payload or {}).get("event_id") != event_id
    ):
        await event.show_snackbar("⌛ Сессия выбора истекла. Начни заново: /reg")
        return

    await _send_sport_page(event, event_id, page)


async def process_back_to_sports(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    state = await state_dispenser.get(event.peer_id)
    event_id = (state.payload or {}).get("event_id") if state is not None else None
    try:
        event_id = int(payload.get("event_id", event_id))
    except (TypeError, ValueError):
        await event.show_snackbar("❌ Не удалось определить мероприятие.")
        return

    if (
        state is None
        or state.state != str(RegistrationState.WAITING_CATEGORY)
        or (state.payload or {}).get("event_id") != event_id
    ):
        await event.show_snackbar("⌛ Сессия выбора истекла. Начни заново: /reg")
        return

    await _send_sport_page(event, event_id, page=0)

async def process_choose_category_page(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        event_id = int(payload["event_id"])
        sport_id = int(payload["sport_id"])
        page = int(payload["page"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректная страница выбора.")
        return

    state = await state_dispenser.get(event.peer_id)
    if (
        state is None
        or state.state != str(RegistrationState.WAITING_CATEGORY)
        or (state.payload or {}).get("event_id") != event_id
        or (state.payload or {}).get("sport_id") != sport_id
    ):
        await event.show_snackbar("⌛ Сессия выбора истекла. Начни заново: /reg")
        return

    await _send_category_page(event, event_id, sport_id, page)


async def _send_category_page(
    event: MessageEvent,
    event_id: int,
    sport_id: int,
    page: int,
    initial: bool = False,
):
    try:
        event_title, event_categories = await _load_event_categories(event_id)
    except Exception:
        logger.exception("Failed to load categories for registration")
        await event.show_snackbar("❌ Не удалось загрузить категории.")
        return

    if event_title is None:
        await event.show_snackbar("❌ Мероприятие не найдено.")
        await state_dispenser.delete(event.peer_id)
        return

    categories = _categories_for_sport(event_categories, sport_id)

    if not categories:
        await event.show_snackbar("📭 Для этого вида спорта нет категорий.")
        return

    last_page = (len(categories) - 1) // MAX_BUTTONS
    if page < 0 or page > last_page:
        await event.show_snackbar("❌ Такой страницы нет.")
        return

    await state_dispenser.set(
        event.peer_id,
        RegistrationState.WAITING_CATEGORY,
        event_id=event_id,
        sport_id=sport_id,
        page=page,
    )
    keyboard = Keyboard(inline=True)
    start = page * MAX_BUTTONS
    for category in categories[start:start + MAX_BUTTONS]:
        label = category["category_title"]
        if category["distance_km"] is not None:
            label = f"{label} — {category['distance_km']} км"
        keyboard.add(
            Callback(
                label[:40],
                payload={
                    "cmd": "reg_category",
                    "event_category_id": category["event_category_id"],
                    "sport_id": sport_id,
                },
            )
        )
        keyboard.row()

    if page > 0:
        keyboard.add(
            Callback(
                "← Назад",
                payload={
                    "cmd": "reg_category_page",
                    "event_id": event_id,
                    "sport_id": sport_id,
                    "page": page - 1,
                },
            )
        )
    if page < last_page:
        keyboard.add(
            Callback(
                "Далее →",
                payload={
                    "cmd": "reg_category_page",
                    "event_id": event_id,
                    "sport_id": sport_id,
                    "page": page + 1,
                },
            )
        )
    if page > 0 or page < last_page:
        keyboard.row()
    keyboard.add(
        Callback(
            "← К видам спорта",
            payload={"cmd": "reg_sports_back", "event_id": event_id},
        )
    )
    keyboard.row()
    keyboard.add(Callback("К мероприятиям", payload={"cmd": "reg_back"}))
    keyboard.row()
    keyboard.add(
        Callback("Отмена", payload={"cmd": "reg_cancel"}),
        color=KeyboardButtonColor.NEGATIVE,
    )

    page_text = f"Страница {page + 1}/{last_page + 1}\n\n" if last_page > 0 else ""
    await event.show_snackbar(
        "Выбран вид спорта" if initial else "Страница открыта"
    )
    await event.send_message(
        f"🏁 {event_title}\n\n{page_text}👇 Теперь выбери категорию:",
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
    if (
        state is None
        or state.state != str(RegistrationState.WAITING_CATEGORY)
    ):
        await event.show_snackbar("⌛ Сессия истекла. Начни заново: /reg")
        return

    payload = payload or _parse_payload(event.payload)
    event_id = (state.payload or {}).get("event_id")
    sport_id = (state.payload or {}).get("sport_id")
    event_category_id = payload.get("event_category_id")
    if event_id is None or sport_id is None or event_category_id is None:
        await event.show_snackbar("❌ Некорректные данные. Начни заново: /reg")
        await state_dispenser.delete(event.peer_id)
        return

    try:
        event_id = int(event_id)
        sport_id = int(sport_id)
        event_category_id = int(event_category_id)
    except (TypeError, ValueError):
        await event.show_snackbar("❌ Некорректные данные. Начни заново: /reg")
        await state_dispenser.delete(event.peer_id)
        return
    try:
        selected_sport_id = int(payload["sport_id"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректный вид спорта. Начни заново: /reg")
        return
    if selected_sport_id != sport_id:
        await event.show_snackbar("❌ Выбранный вид спорта не совпадает с категорией.")
        return

    try:
        async with Session() as session:
            selected_option = await session.scalar(
                select(EventCategory.id).where(
                    EventCategory.id == event_category_id,
                    EventCategory.event_id == event_id,
                    EventCategory.sport_id == sport_id,
                )
            )
    except Exception:
        logger.exception("Failed to validate category/sport before registration")
        await event.show_snackbar("❌ Не удалось проверить категорию. Попробуй позже.")
        return
    if selected_option is None:
        await event.show_snackbar("❌ Категория не относится к выбранному спорту.")
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


@registration_labeler.message(text="/change_sport")
async def start_change_sport(message: Message):
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
        async with Session() as session:
            registrations = list(
                (
                    await session.scalars(
                        select(Registration)
                        .join(Event, Event.id == Registration.event_id)
                        .options(
                            selectinload(Registration.event),
                            selectinload(Registration.event_category).selectinload(
                                EventCategory.category
                            ),
                            selectinload(Registration.event_category).selectinload(
                                EventCategory.sport
                            ),
                        )
                        .where(
                            Registration.user_id == user.id,
                            Event.sport_change_open.is_(True),
                            Event.ends_on >= date.today(),
                        )
                        .order_by(Event.starts_on, Event.title)
                    )
                ).all()
            )

            choices = []
            for registration in registrations:
                current = registration.event_category
                if current is None:
                    continue
                has_alternative = await session.scalar(
                    select(EventCategory.id)
                    .where(
                        EventCategory.event_id == registration.event_id,
                        EventCategory.category_id == current.category_id,
                        EventCategory.sport_id != current.sport_id,
                    )
                    .limit(1)
                )
                if has_alternative is not None:
                    choices.append(
                        {
                            "registration_id": registration.id,
                            "title": registration.event.title,
                            "sport": current.sport.title,
                            "category": current.category.title,
                        }
                    )
    except Exception:
        logger.exception("Failed to load eligible sport changes")
        await message.answer("❌ Не удалось проверить доступные смены спорта.")
        return

    if not choices:
        await message.answer(
            "📭 Сейчас нет регистраций, где можно сменить вид спорта. "
            "Администратор должен открыть смену для события; категория "
            "должна быть доступна и для другого вида спорта."
        )
        return

    keyboard = Keyboard(inline=True)
    for choice in choices:
        label = (
            f"{choice['title'][:18]}: {choice['sport']} / {choice['category']}"
        )[:40]
        keyboard.add(
            Callback(
                label,
                payload={
                    "cmd": "change_sport_registration",
                    "registration_id": choice["registration_id"],
                },
            )
        )
        keyboard.row()
    keyboard.add(
        Callback("Отмена", payload={"cmd": "reg_cancel"}),
        color=KeyboardButtonColor.NEGATIVE,
    )
    await message.answer(
        "Выбери регистрацию, в которой хочешь сменить вид спорта "
        "(категория останется прежней):",
        keyboard=keyboard.get_json(),
    )


async def _show_sport_change_targets(
    event: MessageEvent,
    registration_id: int,
    page: int,
):
    try:
        user = await get_or_create_user(event.ctx_api, event.user_id)
        async with Session() as session:
            registration = await session.scalar(
                select(Registration)
                .join(Event, Event.id == Registration.event_id)
                .options(
                    selectinload(Registration.event),
                    selectinload(Registration.event_category).selectinload(
                        EventCategory.category
                    ),
                    selectinload(Registration.event_category).selectinload(
                        EventCategory.sport
                    ),
                )
                .where(
                    Registration.id == registration_id,
                    Registration.user_id == user.id,
                    Event.sport_change_open.is_(True),
                    Event.ends_on >= date.today(),
                )
            )
            if registration is None or registration.event_category is None:
                await event.show_snackbar(
                    "Смена недоступна: администратор закрыл её или событие завершилось."
                )
                return

            current = registration.event_category
            targets = list(
                (
                    await session.scalars(
                        select(EventCategory)
                        .options(selectinload(EventCategory.sport))
                        .where(
                            EventCategory.event_id == registration.event_id,
                            EventCategory.category_id == current.category_id,
                            EventCategory.sport_id != current.sport_id,
                        )
                        .order_by(EventCategory.sport_id)
                    )
                ).all()
            )
            event_title = registration.event.title
            current_sport = current.sport.title
            category_title = current.category.title
    except Exception:
        logger.exception("Failed to load target sports for registration")
        await event.show_snackbar("❌ Не удалось загрузить доступные виды спорта.")
        return

    if not targets:
        await event.show_snackbar(
            "Для этой категории нет другого доступного вида спорта."
        )
        return

    last_page = (len(targets) - 1) // MAX_BUTTONS
    if page < 0 or page > last_page:
        await event.show_snackbar("❌ Такой страницы нет.")
        return

    keyboard = Keyboard(inline=True)
    start = page * MAX_BUTTONS
    for target in targets[start:start + MAX_BUTTONS]:
        keyboard.add(
            Callback(
                f"{target.sport.title} — {target.distance_km} км"[:40],
                payload={
                    "cmd": "confirm_sport_change",
                    "registration_id": registration_id,
                    "sport_id": target.sport_id,
                },
            )
        )
        keyboard.row()

    if page > 0:
        keyboard.add(
            Callback(
                "← Назад",
                payload={
                    "cmd": "change_sport_targets_page",
                    "registration_id": registration_id,
                    "page": page - 1,
                },
            )
        )
    if page < last_page:
        keyboard.add(
            Callback(
                "Далее →",
                payload={
                    "cmd": "change_sport_targets_page",
                    "registration_id": registration_id,
                    "page": page + 1,
                },
            )
        )
    if page > 0 or page < last_page:
        keyboard.row()
    keyboard.add(Callback("Отмена", payload={"cmd": "change_sport_cancel"}))
    page_text = f"Страница {page + 1}/{last_page + 1}\n\n" if last_page else ""
    await event.send_message(
        f"🏁 {event_title}\n"
        f"🏅 Текущий вид спорта: {current_sport}\n"
        f"📌 Категория останется: {category_title}\n\n"
        f"{page_text}Выбери новый вид спорта:",
        keyboard=keyboard.get_json(),
    )


async def process_change_sport_registration(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        registration_id = int(payload["registration_id"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректная регистрация.")
        return
    await _show_sport_change_targets(event, registration_id, page=0)


async def process_change_sport_targets_page(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        registration_id = int(payload["registration_id"])
        page = int(payload["page"])
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректная страница выбора.")
        return
    await _show_sport_change_targets(event, registration_id, page)


async def process_confirm_sport_change(
    event: MessageEvent,
    payload: dict | None = None,
):
    payload = payload or _parse_payload(event.payload)
    try:
        registration_id = int(payload["registration_id"])
        sport_id = int(payload["sport_id"])
        user = await get_or_create_user(event.ctx_api, event.user_id)
    except (KeyError, TypeError, ValueError):
        await event.show_snackbar("❌ Некорректные данные смены спорта.")
        return
    except Exception:
        logger.exception("Failed to load user for sport change")
        await event.show_snackbar("❌ Не удалось проверить пользователя.")
        return

    try:
        async with Session() as session:
            registration = await session.scalar(
                select(Registration)
                .where(
                    Registration.id == registration_id,
                    Registration.user_id == user.id,
                )
                .with_for_update()
            )
            if registration is None:
                await event.show_snackbar("Регистрация не найдена.")
                return

            event_record = await session.scalar(
                select(Event)
                .where(Event.id == registration.event_id)
                .with_for_update()
            )
            current = await session.get(
                EventCategory, registration.event_category_id
            )
            if (
                event_record is None
                or not event_record.sport_change_open
                or event_record.ends_on < date.today()
                or current is None
            ):
                await event.show_snackbar(
                    "Администратор закрыл смену или событие недоступно."
                )
                return

            target = await session.scalar(
                select(EventCategory)
                .options(selectinload(EventCategory.sport))
                .where(
                    EventCategory.event_id == registration.event_id,
                    EventCategory.category_id == current.category_id,
                    EventCategory.sport_id == sport_id,
                    EventCategory.sport_id != current.sport_id,
                )
            )
            if target is None:
                await event.show_snackbar(
                    "Для этой категории выбранный вид спорта недоступен."
                )
                return

            category_title = await session.scalar(
                select(Category.title).where(Category.id == current.category_id)
            )
            registration.event_category_id = target.id
            await session.commit()
            event_title = event_record.title
            target_sport_title = target.sport.title
    except Exception:
        logger.exception("Failed to change registration sport")
        await event.show_snackbar("❌ Не удалось сменить вид спорта.")
        return

    await event.send_message(
        f"✅ Для события «{event_title}» вид спорта изменён на "
        f"«{target_sport_title}». Категория «{category_title}» сохранена."
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
                selectinload(Registration.event_category).selectinload(
                    EventCategory.category
                ),
                selectinload(Registration.event_category).selectinload(
                    EventCategory.sport
                ),
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

    await event.send_message("\n".join(lines), disable_mentions=True)


async def process_cancel_registration(event: MessageEvent):
    await state_dispenser.delete(event.peer_id)
    await event.show_snackbar("❌ Регистрация отменена.")