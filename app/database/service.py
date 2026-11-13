import logging

from datetime import date
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.db import async_session_factory as Session
from app.database.models import User, Event, EventType, EventCategory

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """Исключение для отказа в доступе."""
    pass


async def get_user_by_vk_id(session: AsyncSession, vk_id: int) -> User | None:
    """Только БД: найти по vk_id."""
    return await session.scalar(select(User).where(User.vk_id == vk_id))


async def create_user(session: AsyncSession, profile: dict) -> User:
    """Только БД: создать. profile — то, что вернул fetch_vk_profile."""
    user = User(
        vk_id=profile["user_vk_id"],
        first_name=profile["first_name"],
        last_name=profile["last_name"],
    )
    session.add(user)
    await session.flush()   # получить id, не коммитя
    return user


def event_is_registration_available(
    starts_on: date,
    ends_on: date,
    registration_open: bool,
    current_date: date | None = None,
) -> bool:
    """Регистрация доступна, если она открыта и событие ещё не закончилось."""
    today = current_date or date.today()
    return bool(registration_open) and ends_on >= today and ends_on > starts_on


def event_is_report_available(
    starts_on: date,
    ends_on: date,
    registration_open: bool,
    current_date: date | None = None,
) -> bool:
    """Отчёт можно сдавать только в уже начавшееся событие независимо от статуса регистрации."""
    today = current_date or date.today()
    return starts_on <= today <= ends_on


async def get_registration_events(session: AsyncSession) -> list[Event]:
    """События, на которые можно регистрироваться прямо сейчас."""
    query = (
        select(Event)
        .options(
            selectinload(Event.event_categories).selectinload(
                EventCategory.category)
        )
        .where(
            Event.registration_open == True,
            Event.ends_on >= func.current_date(),
        )
        .order_by(Event.starts_on.asc(), Event.title.asc())
    )
    result = await session.execute(query)
    return list(result.scalars().unique().all())


async def get_active_events(session: AsyncSession) -> list[Event]:
    """Актуальные события: уже начавшиеся или ещё не начавшиеся, но с открытой регистрацией."""
    query = (
        select(Event)
        .options(
            selectinload(Event.event_categories).selectinload(
                EventCategory.category)
        )
        .where(
            or_(
                (Event.starts_on <= func.current_date())
                & (Event.ends_on >= func.current_date()),
                (Event.registration_open == True)
                & (Event.starts_on > func.current_date()),
            )
        )
        .order_by(Event.starts_on.asc(), Event.title.asc())
    )
    result = await session.execute(query)
    return list(result.scalars().unique().all())


async def create_new_event(
    session: AsyncSession,
    vk_id: int,
    title: str,
    starts_on: date,
    ends_on: date,
    event_type: EventType,
    runs_per_week: int | None = None,
    registration_open: bool = False
) -> Event:
    """
    Создает новое событие.
    Выбрасывает PermissionDeniedError, если пользователь не админ.
    """
    # 1. Строгая проверка прав администратора через БД
    user_query = select(User).where(User.vk_id == vk_id)
    user_result = await session.execute(user_query)
    user = user_result.scalar_one_or_none()

    if not user or not user.is_admin:
        raise PermissionDeniedError("У вас нет прав для создания событий.")

    # 2. Создание объекта события
    # Примечание: CheckConstraint "check_events_period" (ends_on > starts_on)
    # и "check_event_type_runs_per_week" уже защитят вас на уровне БД,
    # но можно добавить предварительную проверку и здесь для быстрого ответа.
    if starts_on >= ends_on:
        raise ValueError(
            "Дата окончания должна быть строго позже даты начала.")

    new_event = Event(
        title=title,
        starts_on=starts_on,
        ends_on=ends_on,
        event_type=event_type,
        runs_per_week=runs_per_week,
        registration_open=registration_open
    )

    session.add(new_event)

    # 3. Сохранение и обработка возможных конфликтов БД
    try:
        await session.commit()
        # Получаем актуальный объект с присвоенным ID
        await session.refresh(new_event)
        return new_event
    except IntegrityError:
        await session.rollback()
        # Сработает, если нарушен UniqueConstraint("title", "starts_on")
        raise ValueError(
            "Событие с таким названием и датой начала уже существует.")
