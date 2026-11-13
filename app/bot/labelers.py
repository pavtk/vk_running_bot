# app/bot/labelers.py
from vkbottle.bot import BotLabeler

# Один labeler на весь event-creation flow.
# Здесь же можно завести остальные labeler'ы (profile, reminders и т.д.)
event_creation_labeler = BotLabeler()
event_show_labeler = BotLabeler()
registration_labeler = BotLabeler()
registrations_show_labeler = BotLabeler()
report_labeler = BotLabeler()
stats_labeler = BotLabeler()
help_labeler = BotLabeler()
