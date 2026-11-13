from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from vkbottle.bot import Message, BotLabeler

from app.logger import logger
from app.bot.handlers.states import EventCreateState
from app.database.models import Category, Event, EventCategory
from app.service import get_or_create_user
from app.database.service import EventType, Session
from app.bot.utils import _get_state_payload, _text, require_private_message
from app.bot.labelers import event_creation_labeler
from app.bot.handlers.states import state_dispenser

EVENT_TYPE_MAP = {
    "1": EventType.RUNS_PER_WEEK,
    "2": EventType.DISTANCE,
}


@event_creation_labeler.message(lev="/create_event")
async def start_create_event(message: Message):
    """Начало создания события. Проверка прав админа."""
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("get_or_create_user failed for /create_event")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    # Защита от повторного входа в активное состояние
    if await state_dispenser.get(message.peer_id) is not None:
        await message.answer(
            "⚠️ Уже идёт создание события.\n"
            "Продолжи или отмени командой /cancel."
        )
        return

    await state_dispenser.set(message.peer_id, EventCreateState.WAITING_TITLE)
    await message.answer(
        "🏃 Создание нового события\n\n"
        "Введи название события (до 100 символов):"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_TITLE)
async def process_title(message: Message):
    title = _text(message)
    if not title or len(title) > 100:
        await message.answer(
            "⚠️ Название должно быть от 1 до 100 символов.\n"
            "Попробуй ещё раз:"
        )
        return

    payload = await _get_state_payload(message)
    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_START_DATE,
        **payload,
        title=title,
    )
    await message.answer(
        "📅 Введи дату начала события в формате ГГГГ-ММ-ДД\n"
        "(например: 2026-11-15):"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_START_DATE)
async def process_start_date(message: Message):
    text = _text(message)
    try:
        starts_on = datetime.strptime(text, "%Y-%m-%d").date()
        if starts_on < date.today():
            raise ValueError("Дата не может быть в прошлом")
    except ValueError as e:
        error_msg = str(e) if "прошлом" in str(e) else "Неверный формат даты"
        await message.answer(
            f"⚠️ {error_msg}\n"
            "Введи дату в формате ГГГГ-ММ-ДД (например: 2026-11-15):"
        )
        return

    payload = await _get_state_payload(message)
    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_END_DATE,
        **payload,
        starts_on=starts_on.isoformat(),
    )
    await message.answer(
        "📅 Введи дату окончания события в формате ГГГГ-ММ-ДД\n"
        "(должна быть позже даты начала):"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_END_DATE)
async def process_end_date(message: Message):
    text = _text(message)
    payload = await _get_state_payload(message)

    starts_on_raw = payload.get("starts_on")
    if not starts_on_raw:
        await message.answer("❌ Потеряны данные о дате начала. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    try:
        starts_on = datetime.fromisoformat(starts_on_raw).date()
        ends_on = datetime.strptime(text, "%Y-%m-%d").date()
        if ends_on <= starts_on:
            raise ValueError("Дата окончания должна быть позже даты начала")
    except ValueError as e:
        error_msg = str(e) if "позже" in str(e) else "Неверный формат даты"
        await message.answer(
            f"⚠️ {error_msg}\n"
            "Введи дату в формате ГГГГ-ММ-ДД:"
        )
        return

    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_EVENT_TYPE,
        **payload,
        ends_on=ends_on.isoformat(),
    )
    await message.answer(
        "🎯 Выбери тип события:\n"
        "1) Пробежки в неделю (runs_per_week)\n"
        "2) Дистанция (distance)"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_EVENT_TYPE)
async def process_event_type(message: Message):
    text = _text(message)
    event_type = EVENT_TYPE_MAP.get(text)
    if event_type is None:
        await message.answer(
            "⚠️ Пожалуйста, выбери 1 или 2:\n"
            "1) Пробежки в неделю\n"
            "2) Дистанция"
        )
        return

    payload = await _get_state_payload(message)

    if event_type == EventType.RUNS_PER_WEEK:
        await state_dispenser.set(
            message.peer_id,
            EventCreateState.WAITING_RUNS_PER_WEEK,
            **payload,
            event_type=event_type.value,
        )
        await message.answer(
            "🏃 Сколько пробежек в неделю нужно сделать?\n"
            "(введи число больше 0):"
        )
    else:
        await state_dispenser.set(
            message.peer_id,
            EventCreateState.WAITING_REGISTRATION_OPEN,
            **payload,
            event_type=event_type.value,
            runs_per_week=None,
        )
        await message.answer(
            "🔓 Открыть регистрацию сразу?\n"
            "1) Да\n"
            "2) Нет"
        )


@event_creation_labeler.message(state=EventCreateState.WAITING_RUNS_PER_WEEK)
async def process_runs_per_week(message: Message):
    try:
        runs_per_week = int(_text(message))
        if runs_per_week <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи целое число больше 0:")
        return

    payload = await _get_state_payload(message)
    payload.pop("runs_per_week", None)   # ← защита от дубля

    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_REGISTRATION_OPEN,
        **payload,
        runs_per_week=runs_per_week,
    )
    await message.answer(
        "🔓 Открыть регистрацию сразу?\n"
        "1) Да\n"
        "2) Нет"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_REGISTRATION_OPEN)
async def process_registration_open(message: Message):
    text = _text(message)
    if text not in ("1", "2"):
        await message.answer(
            "⚠️ Пожалуйста, выбери 1 или 2:\n"
            "1) Да\n"
            "2) Нет"
        )
        return

    registration_open = (text == "1")
    payload = await _get_state_payload(message)

    # Валидация обязательных полей
    try:
        title = payload["title"]
        starts_on = datetime.fromisoformat(payload["starts_on"]).date()
        ends_on = datetime.fromisoformat(payload["ends_on"]).date()
        event_type = EventType(payload["event_type"])
    except (KeyError, ValueError):
        await message.answer("❌ Потеряны данные. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    runs_per_week = payload.get("runs_per_week")
    if event_type == EventType.RUNS_PER_WEEK and not runs_per_week:
        await message.answer("❌ Не задано число пробежек. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    event_id = None
    try:
        async with Session() as session:
            new_event = Event(
                title=title,
                starts_on=starts_on,
                ends_on=ends_on,
                event_type=event_type,
                runs_per_week=runs_per_week,
                registration_open=registration_open,
            )
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)
            # важно: сохраняем id до закрытия сессии
            event_id = new_event.id
    except IntegrityError:
        await message.answer(
            "❌ Событие с таким названием и датой начала уже существует.\n"
            "Придётся начать заново с другим названием.\n\n"
            "Введи название события:"
        )
        await state_dispenser.set(message.peer_id, EventCreateState.WAITING_TITLE)
        return
    except Exception:
        logger.exception("Error creating event")
        await message.answer("❌ Произошла ошибка. Попробуй позже.")
        return

    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_ADD_CATEGORY,
        **payload,
        registration_open=registration_open,
        event_id=event_id,
        added_categories=[],
    )

    await message.answer(
        f"✅ Событие '{title}' создано (ID: {event_id})!\n\n"
        f"Теперь нужно добавить хотя бы одну категорию для этого события.\n"
        f"Добавить категорию?\n"
        f"1) Да\n"
        f"2) Нет (завершить создание)"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_ADD_CATEGORY)
async def process_add_category_choice(message: Message):
    text = _text(message)
    if text not in ("1", "2"):
        await message.answer(
            "⚠️ Выбери 1 или 2:\n"
            "1) Да\n"
            "2) Нет (завершить)"
        )
        return

    payload = await _get_state_payload(message)
    if "event_id" not in payload:
        await message.answer("❌ Потеряны данные события. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    if text == "2":
        await finish_event_creation(message, payload)
        return

    try:
        async with Session() as session:
            result = await session.execute(select(Category).order_by(Category.id))
            categories = result.scalars().all()
    except Exception:
        logger.exception("Failed to load categories")
        await message.answer("❌ Не удалось загрузить категории. Попробуй позже.")
        return

    if not categories:
        await message.answer(
            "⚠️ В базе нет ни одной категории. "
            "Сначала создай категории, а потом возвращайся к событию."
        )
        await finish_event_creation(message, payload)
        return

    categories_data = [{"id": c.id, "title": c.title} for c in categories]
    categories_list = "\n".join(
        f"{i+1}) {c['title']}" for i, c in enumerate(categories_data))

    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_CATEGORY_SELECT,
        **payload,
        categories_list=categories_data,
    )
    await message.answer(
        f"📂 Выбери категорию:\n{categories_list}\n\n"
        f"Введи номер категории:"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_CATEGORY_SELECT)
async def process_category_select(message: Message):
    payload = await _get_state_payload(message)
    categories_data = payload.get("categories_list") or []
    if not categories_data:
        await message.answer("❌ Список категорий потерян. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    try:
        idx = int(_text(message)) - 1
        if not (0 <= idx < len(categories_data)):
            raise ValueError
    except ValueError:
        await message.answer(f"⚠️ Введи число от 1 до {len(categories_data)}:")
        return

    selected = categories_data[idx]
    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_CATEGORY_DISTANCE,
        **payload,
        selected_category_id=selected["id"],
        selected_category_title=selected["title"],
    )

    event_type = payload.get("event_type")
    distance_hint = (
        "минимальную"
        if event_type == EventType.RUNS_PER_WEEK.value
        else "целевую"
    )
    await message.answer(
        f"📏 Введи {distance_hint} дистанцию для категории "
        f"'{selected['title']}' (в км, например: 5, 10.5, 42.195):"
    )


@event_creation_labeler.message(state=EventCreateState.WAITING_CATEGORY_DISTANCE)
async def process_category_distance(message: Message):
    payload = await _get_state_payload(message)

    event_id = payload.get("event_id")
    category_id = payload.get("selected_category_id")
    category_title = payload.get("selected_category_title")
    if event_id is None or category_id is None or category_title is None:
        await message.answer("❌ Потеряны данные. Начни заново: /create_event")
        await state_dispenser.delete(message.peer_id)
        return

    text = _text(message).replace(",", ".")
    try:
        distance_km = Decimal(text)
        if distance_km <= 0:
            raise ValueError
        if distance_km > Decimal("9999.99"):
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer(
            "⚠️ Введи положительное число (например: 5, 10.5, 42.195):"
        )
        return

    try:
        async with Session() as session:
            session.add(EventCategory(
                event_id=event_id,
                category_id=category_id,
                distance_km=distance_km,
            ))
            await session.commit()
    except IntegrityError:
        # Категория уже привязана — возвращаемся к выбору
        categories_data = payload.get("categories_list") or []
        if not categories_data:
            await message.answer("❌ Список категорий потерян. Начни заново: /create_event")
            await state_dispenser.delete(message.peer_id)
            return
        categories_list = "\n".join(
            f"{i+1}) {c['title']}" for i, c in enumerate(categories_data)
        )
        # сбрасываем выбранную категорию, чтобы можно было выбрать другую
        for key in ("selected_category_id", "selected_category_title"):
            payload.pop(key, None)
        await state_dispenser.set(
            message.peer_id,
            EventCreateState.WAITING_CATEGORY_SELECT,
            **payload,
        )
        await message.answer(
            "⚠️ Эта категория уже добавлена к данному событию.\n\n"
            f"📂 Выбери другую категорию:\n{categories_list}"
        )
        return
    except Exception:
        logger.exception("Error saving event category")
        await message.answer("❌ Ошибка при сохранении. Попробуй снова.")
        return

    # Успех — обновляем payload
    added_categories = list(payload.get("added_categories") or [])
    added_categories.append({
        "title": category_title,
        "distance_km": str(distance_km),
    })
    payload["added_categories"] = added_categories
    for key in ("categories_list", "selected_category_id", "selected_category_title"):
        payload.pop(key, None)

    await state_dispenser.set(
        message.peer_id,
        EventCreateState.WAITING_ADD_CATEGORY,
        **payload,
    )

    await message.answer(
        f"✅ Категория '{category_title}' с дистанцией {distance_km} км добавлена!\n\n"
        f"Добавить ещё категорию?\n"
        f"1) Да\n"
        f"2) Нет (завершить)"
    )


async def finish_event_creation(message: Message, payload: dict):
    """Завершение создания события — итоговое сообщение."""
    await state_dispenser.delete(message.peer_id)

    try:
        starts_on = datetime.fromisoformat(payload["starts_on"]).date()
        ends_on = datetime.fromisoformat(payload["ends_on"]).date()
        event_type = EventType(payload["event_type"])
    except (KeyError, ValueError):
        await message.answer("⚠️ Не удалось восстановить данные события.")
        return

    type_text = "Пробежки в неделю" if event_type == EventType.RUNS_PER_WEEK else "Дистанция"
    runs_text = (
        f"\n• Пробежек в неделю: {payload['runs_per_week']}"
        if payload.get("runs_per_week") else ""
    )

    added_categories = payload.get("added_categories") or []
    if added_categories:
        categories_text = "\n\n📂 Категории:\n• " + "\n• ".join(
            f"{c['title']} — {c['distance_km']} км" for c in added_categories
        )
    else:
        categories_text = "\n\n⚠️ Категории не добавлены"

    await message.answer(
        f"🎉 Создание события завершено!\n\n"
        f"📋 Детали:\n"
        f"• ID: {payload.get('event_id', '?')}\n"
        f"• Название: {payload.get('title', '?')}\n"
        f"• Период: {starts_on} — {ends_on}\n"
        f"• Тип: {type_text}{runs_text}\n"
        f"• Регистрация: {'открыта' if payload.get('registration_open') else 'закрыта'}"
        f"{categories_text}"
    )
