from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from vkbottle.bot import Message

from app.bot.handlers.states import CatalogState, state_dispenser
from app.bot.labelers import catalog_labeler
from app.bot.utils import _get_state_payload, _text, require_private_message
from app.database.models import Category, CategorySportDistance, Sport
from app.database.service import Session
from app.logger import logger
from app.service import get_or_create_user


async def _show_catalog_menu(message: Message, notice: str | None = None):
    await state_dispenser.set(message.peer_id, CatalogState.WAITING_ACTION)
    prefix = f"{notice}\n\n" if notice else ""
    await message.answer(
        f"{prefix}⚙️ Настройка справочника:\n"
        "1) Добавить категорию\n"
        "2) Добавить вид спорта\n"
        "3) Задать дистанцию для пары «категория + вид спорта»\n"
        "4) Показать справочник\n"
        "0) Завершить\n\n"
        "Введи номер действия:"
    )


@catalog_labeler.message(lev="/catalog")
async def start_catalog_management(message: Message):
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        logger.exception("get_or_create_user failed for /catalog")
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.")
        return

    if not user.is_admin:
        await message.answer("❌ Эта команда доступна только администраторам.")
        return

    if await state_dispenser.get(message.peer_id) is not None:
        await message.answer(
            "⚠️ Уже идёт другой сценарий. Продолжи его или отмени командой /cancel."
        )
        return

    await _show_catalog_menu(message)


@catalog_labeler.message(state=CatalogState.WAITING_ACTION)
async def process_catalog_action(message: Message):
    action = _text(message)
    if action == "0":
        await state_dispenser.delete(message.peer_id)
        await message.answer("Настройка справочника завершена.")
    elif action == "1":
        await state_dispenser.set(
            message.peer_id, CatalogState.WAITING_CATEGORY_TITLE
        )
        await message.answer("Введи название категории (до 30 символов):")
    elif action == "2":
        try:
            async with Session() as session:
                has_categories = await session.scalar(
                    select(Category.id).limit(1)
                )
        except Exception:
            logger.exception("Failed to check categories before adding a sport")
            await message.answer("❌ Не удалось проверить категории. Попробуй позже.")
            return
        if has_categories is None:
            await _show_catalog_menu(
                message,
                "Сначала добавь хотя бы одну категорию, затем виды спорта.",
            )
            return
        await state_dispenser.set(message.peer_id, CatalogState.WAITING_SPORT_TITLE)
        await message.answer("Введи название вида спорта (до 50 символов):")
    elif action == "3":
        await _ask_distance_pair(message)
    elif action == "4":
        await _send_catalog(message)
        await _show_catalog_menu(message)
    else:
        await message.answer("⚠️ Введи 1, 2, 3, 4 или 0.")


@catalog_labeler.message(state=CatalogState.WAITING_CATEGORY_TITLE)
async def process_catalog_category_title(message: Message):
    title = _text(message).strip()
    if not title or len(title) > 30:
        await message.answer("⚠️ Название категории должно быть от 1 до 30 символов:")
        return

    try:
        async with Session() as session:
            session.add(Category(title=title))
            await session.commit()
    except IntegrityError:
        await message.answer("⚠️ Такая категория уже существует. Введи другое название:")
        return
    except Exception:
        logger.exception("Error creating category from /catalog")
        await message.answer("❌ Не удалось сохранить категорию. Попробуй позже.")
        return

    await _show_catalog_menu(message, f"✅ Категория «{title}» добавлена.")


@catalog_labeler.message(state=CatalogState.WAITING_SPORT_TITLE)
async def process_catalog_sport_title(message: Message):
    title = _text(message).strip()
    if not title or len(title) > 50:
        await message.answer("⚠️ Название вида спорта должно быть от 1 до 50 символов:")
        return

    try:
        async with Session() as session:
            session.add(Sport(title=title))
            await session.commit()
    except IntegrityError:
        await message.answer("⚠️ Такой вид спорта уже существует. Введи другое название:")
        return
    except Exception:
        logger.exception("Error creating sport from /catalog")
        await message.answer("❌ Не удалось сохранить вид спорта. Попробуй позже.")
        return

    await _show_catalog_menu(message, f"✅ Вид спорта «{title}» добавлен.")


async def _ask_distance_pair(message: Message):
    try:
        async with Session() as session:
            categories = list(
                (await session.scalars(select(Category).order_by(Category.title))).all()
            )
            sports = list(
                (await session.scalars(select(Sport).order_by(Sport.title))).all()
            )
    except Exception:
        logger.exception("Failed to load catalog for distance setup")
        await message.answer("❌ Не удалось загрузить справочник. Попробуй позже.")
        return

    if not categories or not sports:
        await _show_catalog_menu(
            message,
            "Сначала добавь хотя бы одну категорию и один вид спорта.",
        )
        return

    category_list = [{"id": item.id, "title": item.title} for item in categories]
    sport_list = [{"id": item.id, "title": item.title} for item in sports]
    categories_text = "\n".join(
        f"{index}. {item['title']}" for index, item in enumerate(category_list, 1)
    )
    sports_text = "\n".join(
        f"{index}. {item['title']}" for index, item in enumerate(sport_list, 1)
    )
    await state_dispenser.set(
        message.peer_id,
        CatalogState.WAITING_DISTANCE_PAIR,
        categories=category_list,
        sports=sport_list,
    )
    await message.answer(
        f"📂 Категории:\n{categories_text}\n\n"
        f"🏅 Виды спорта:\n{sports_text}\n\n"
        "Введи номера через пробел: сначала категория, затем вид спорта "
        "(например: 1 2):"
    )


@catalog_labeler.message(state=CatalogState.WAITING_DISTANCE_PAIR)
async def process_catalog_distance_pair(message: Message):
    payload = await _get_state_payload(message)
    categories = payload.get("categories") or []
    sports = payload.get("sports") or []
    parts = _text(message).split()
    if len(parts) != 2:
        await message.answer("⚠️ Введи два номера через пробел, например: 1 2")
        return

    try:
        category_index, sport_index = (int(part) - 1 for part in parts)
        category = categories[category_index]
        sport = sports[sport_index]
    except (ValueError, IndexError):
        await message.answer(
            f"⚠️ Выбери категорию от 1 до {len(categories)} и спорт от 1 до {len(sports)}."
        )
        return

    await state_dispenser.set(
        message.peer_id,
        CatalogState.WAITING_DISTANCE_VALUE,
        category_id=category["id"],
        category_title=category["title"],
        sport_id=sport["id"],
        sport_title=sport["title"],
    )
    await message.answer(
        f"Введи фиксированную дистанцию в км для "
        f"«{category['title']} + {sport['title']}» (например, 5 или 10.5):"
    )


@catalog_labeler.message(state=CatalogState.WAITING_DISTANCE_VALUE)
async def process_catalog_distance_value(message: Message):
    payload = await _get_state_payload(message)
    try:
        category_id = int(payload["category_id"])
        sport_id = int(payload["sport_id"])
        category_title = payload["category_title"]
        sport_title = payload["sport_title"]
    except (KeyError, TypeError, ValueError):
        await state_dispenser.delete(message.peer_id)
        await message.answer("❌ Данные потеряны. Запусти /catalog заново.")
        return

    try:
        distance_km = Decimal(_text(message).replace(",", "."))
        if (
            distance_km <= 0
            or distance_km > Decimal("9999.99")
            or distance_km != distance_km.quantize(Decimal("0.01"))
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer(
            "⚠️ Введи число больше 0, не больше 9999.99 и максимум "
            "с двумя знаками после запятой:"
        )
        return

    try:
        async with Session() as session:
            configured_distance = await session.scalar(
                select(CategorySportDistance).where(
                    CategorySportDistance.category_id == category_id,
                    CategorySportDistance.sport_id == sport_id,
                )
            )
            if configured_distance is None:
                configured_distance = CategorySportDistance(
                    category_id=category_id,
                    sport_id=sport_id,
                    distance_km=distance_km,
                )
                session.add(configured_distance)
            else:
                configured_distance.distance_km = distance_km
            await session.commit()
    except IntegrityError:
        logger.exception("Concurrent category/sport distance setup")
        await message.answer(
            "❌ Не удалось сохранить дистанцию из-за параллельного изменения. "
            "Повтори настройку."
        )
        return
    except Exception:
        logger.exception("Error saving category/sport distance")
        await message.answer("❌ Не удалось сохранить дистанцию. Попробуй позже.")
        return

    await _show_catalog_menu(
        message,
        f"✅ Для «{category_title} + {sport_title}» задана дистанция "
        f"{distance_km} км.",
    )


async def _send_catalog(message: Message):
    try:
        async with Session() as session:
            categories = list(
                (await session.scalars(select(Category).order_by(Category.title))).all()
            )
            sports = list(
                (await session.scalars(select(Sport).order_by(Sport.title))).all()
            )
            distances = list(
                (
                    await session.scalars(
                        select(CategorySportDistance).options(
                            selectinload(CategorySportDistance.category),
                            selectinload(CategorySportDistance.sport),
                        )
                    )
                ).all()
            )
    except Exception:
        logger.exception("Failed to display catalog")
        await message.answer("❌ Не удалось загрузить справочник. Попробуй позже.")
        return

    category_text = ", ".join(item.title for item in categories) or "нет"
    sport_text = ", ".join(item.title for item in sports) or "нет"
    distance_lines = [
        f"• {item.category.title} + {item.sport.title} — "
        f"{item.distance_km} км" if item.distance_km is not None
        else f"• {item.category.title} + {item.sport.title} — дистанция не задана"
        for item in distances
    ]
    await message.answer(
        "📚 Справочник\n"
        f"Категории: {category_text}\n"
        f"Виды спорта: {sport_text}\n"
        "Дистанции:\n" + ("\n".join(distance_lines) if distance_lines else "• не заданы")
    )
