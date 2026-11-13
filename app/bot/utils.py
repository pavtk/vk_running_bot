from vkbottle.bot import Message

from app.bot.handlers.states import state_dispenser


def is_private_chat(peer_id: int, user_id: int) -> bool:
    return peer_id == user_id


async def require_private_message(message: Message) -> bool:
    if is_private_chat(message.peer_id, message.from_id):
        return True

    await message.answer("⚠️ Эту команду можно использовать только в личных сообщениях боту.")
    return False


def _text(message: Message) -> str:
    """Безопасное извлечение текста (None → '')."""
    return (message.text or "").strip()


async def _get_state_payload(message: Message) -> dict:
    """Безопасно получить payload текущего состояния (копию)."""
    state = await state_dispenser.get(message.peer_id)
    if state is None:
        return {}
    # dict(...) — поверхностная копия, чтобы не мутировать оригинал
    return dict(state.payload or {})
