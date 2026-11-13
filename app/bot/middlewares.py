from vkbottle.bot import Message
from vkbottle.dispatch.middlewares import BaseMiddleware

from app.bot.utils import state_owner_matches


class StateOwnerMiddleware(BaseMiddleware[Message]):
    async def pre(self) -> None:
        if state_owner_matches(self.event.state_peer, self.event.from_id):
            return

        await self.event.answer(
            "⚠️ Этот сценарий начат другим участником. "
            "Продолжить или отменить его может только автор."
        )
        self.stop()