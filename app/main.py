

from vkbottle.bot import Bot, BotLabeler


from app.settings import settings
from app.bot.handlers.states import state_dispenser
from app.bot.state_storage import UserScopedMessageView

from app.bot.handlers.cancel import cancel_labeler
from app.bot.handlers.catalog import catalog_labeler
from app.bot.handlers.event_creation import event_creation_labeler
from app.bot.handlers.events_show import event_show_labeler
from app.bot.handlers.help import help_labeler
from app.bot.handlers.registration import registration_labeler
from app.bot.handlers.registration_toggle import event_management_labeler
from app.bot.handlers.report import handle_report
from app.bot.handlers.show_registrations import registrations_show_labeler
from app.bot.handlers.stats import stats_labeler
from app.bot.labelers import report_labeler

bot = Bot(
    token=settings.VK_TOKEN,
    state_dispenser=state_dispenser,
    labeler=BotLabeler(message_view=UserScopedMessageView()),
)


bot.labeler.load(cancel_labeler)
bot.labeler.load(catalog_labeler)
bot.labeler.load(event_creation_labeler)
bot.labeler.load(event_show_labeler)
bot.labeler.load(help_labeler)
bot.labeler.load(registration_labeler)
bot.labeler.load(event_management_labeler)
bot.labeler.load(registrations_show_labeler)
bot.labeler.load(report_labeler)
bot.labeler.load(stats_labeler)

# Запускаем бота
if __name__ == "__main__":
    bot.run()
