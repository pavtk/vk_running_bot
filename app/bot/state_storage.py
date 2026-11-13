from vkbottle.dispatch.views.bot.message import BotMessageView

from app.bot.handlers.states import state_dispenser


def user_state_key(peer_id: int, user_id: int) -> int:
    """Map a chat and user pair to a collision-free non-negative integer key."""
    first = peer_id * 2 if peer_id >= 0 else -peer_id * 2 - 1
    second = user_id * 2 if user_id >= 0 else -user_id * 2 - 1
    total = first + second
    return total * (total + 1) // 2 + second


def message_state_key(peer_id: int, user_id: int) -> int:
    """Keep private-chat keys compatible and isolate users in group chats."""
    if peer_id == user_id:
        return peer_id
    return user_state_key(peer_id, user_id)


class UserScopedMessageView(BotMessageView):
    def get_state_key(self, message):
        return message_state_key(message.peer_id, message.from_id)


async def get_user_state(peer_id: int, user_id: int):
    return await state_dispenser.get(message_state_key(peer_id, user_id))


async def set_user_state(peer_id: int, user_id: int, state, **payload):
    await state_dispenser.set(message_state_key(peer_id, user_id), state, **payload)


async def delete_user_state(peer_id: int, user_id: int):
    await state_dispenser.delete(message_state_key(peer_id, user_id))