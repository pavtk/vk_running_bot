from vkbottle.bot import Message

from app.bot.labelers import help_labeler
from app.service import get_or_create_user
from app.bot.utils import require_private_message


@help_labeler.message(text="/help")
async def show_help(message: Message):
    """Показывает список доступных команд в зависимости от роли пользователя."""
    if not await require_private_message(message):
        return

    try:
        user = await get_or_create_user(message.ctx_api, message.from_id)
    except Exception:
        await message.answer("❌ Не удалось получить данные пользователя. Попробуй позже.", disable_mentions=True)
        return

    lines = [
        "📘 Доступные команды:\n",
        "• /events — список активных мероприятий",
        "• /reg — регистрация на событие",
        "• /my_regs — мои регистрации",
        "• /stats — статистика по твоим участиям",
    ]

    if user.is_admin:
        lines.extend([
            "",
            "🛠 Команды администратора:",
            "• /create_event — создать новое событие",
            "• /open — открыть регистрацию на мероприятие",
            "• /close — закрыть регистрацию на мероприятие",
            "• /event_report — общий отчёт по мероприятию",
            "• /cancel — отменить текущий сценарий",
        ])

    await message.answer("\n".join(lines), disable_mentions=True)
