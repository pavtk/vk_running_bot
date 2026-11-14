from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.service import (
    create_user,
    get_user_by_vk_id,
    Session,
    get_active_events,
    get_registration_events,
)
from app.database.models import Event, User


def serialize_event(event: Event) -> dict:
    return {
        'id': event.id,
        'title': event.title,
        'starts_on': event.starts_on,
        'ends_on': event.ends_on,
        'event_categories': [
            {
                'id': ec.id,
                'category_title': ec.category.title,
                'sport_title': ec.sport.title,
                'distance_km': ec.distance_km,
            }
            for ec in event.event_categories
        ],
    }


def serialize_events(events: Iterable[Event]) -> list[dict]:
    return [serialize_event(event) for event in events]


async def get_vk_profile(api, from_id: int) -> dict:
    try:
        user_info = await api.users.get(
            user_ids=from_id,
            fields="first_name,last_name",
        )
        user = user_info[0]
    except Exception as e:
        print("Ошибка получения данных пользователя:", e)
        return {
            'user_vk_id': from_id,
            'first_name': 'Пользователь',
            'last_name': str(from_id),
        }
    return {
        'user_vk_id': from_id,
        'first_name': user.first_name,
        'last_name': user.last_name
    }


async def get_or_create_user(api, vk_id: int) -> User:
    """
    Сценарий на каждое обращение:
      1. ищем в БД — есть, выходим;
      2. нет — тянем из VK;
      3. создаём в БД.
    """
    async with Session() as session:
        user = await get_user_by_vk_id(session, vk_id)
        if user is not None:
            if (user.first_name, user.last_name) == (
                'Пользователь',
                str(vk_id),
            ):
                profile = await get_vk_profile(api, vk_id)
                if (profile['first_name'], profile['last_name']) != (
                    'Пользователь',
                    str(vk_id),
                ):
                    user.first_name = profile['first_name']
                    user.last_name = profile['last_name']
                    await session.commit()
            return user

        profile = await get_vk_profile(api, vk_id)
        user = await create_user(session, profile)
        await session.commit()
        return user


async def render_registration_events(bot, vk_id: int) -> list[dict]:
    async with Session() as session:
        events = await get_registration_events(session)
    return serialize_events(events)


async def render_active_events(bot, vk_id: int) -> list[dict]:
    async with Session() as session:
        events = await get_active_events(session)
    return serialize_events(events)
