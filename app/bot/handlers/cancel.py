from vkbottle.bot import BotLabeler, Message

from app.bot.handlers.states import (
    CatalogState,
    EventCreateState,
    GeneralReportState,
    RegistrationState,
    ReportState,
    StatsState,
    state_dispenser,
)
from app.bot.utils import require_private_message

cancel_labeler = BotLabeler()


@cancel_labeler.message(lev="/cancel", state=[
    EventCreateState.WAITING_TITLE,
    EventCreateState.WAITING_START_DATE,
    EventCreateState.WAITING_END_DATE,
    EventCreateState.WAITING_EVENT_TYPE,
    EventCreateState.WAITING_RUNS_PER_WEEK,
    EventCreateState.WAITING_REGISTRATION_OPEN,
    EventCreateState.WAITING_ADD_CATEGORY,
    EventCreateState.WAITING_CATEGORY_SELECT,
    CatalogState.WAITING_ACTION,
    CatalogState.WAITING_CATEGORY_TITLE,
    CatalogState.WAITING_SPORT_TITLE,
    CatalogState.WAITING_DISTANCE_PAIR,
    CatalogState.WAITING_DISTANCE_VALUE,
    RegistrationState.WAITING_EVENT,
    RegistrationState.WAITING_SPORT,
    RegistrationState.WAITING_CATEGORY,
    StatsState.WAITING_EVENT,
    GeneralReportState.WAITING_EVENT,
    GeneralReportState.WAITING_CATEGORY,
    ReportState.WAITING_CHALLENGE,
])
async def cancel_event_creation(message: Message):
    """Отмена текущего сценария: создание события, регистрации, отчёта и статистики."""
    if not await require_private_message(message):
        return

    await state_dispenser.delete(message.peer_id)
    await message.answer("Сценарий отменён.")