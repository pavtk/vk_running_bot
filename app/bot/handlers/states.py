from vkbottle import BaseStateGroup
from vkbottle.dispatch.dispenser import BuiltinStateDispenser

state_dispenser = BuiltinStateDispenser()

class EventCreateState(BaseStateGroup):
    WAITING_TITLE = "waiting_title"
    WAITING_START_DATE = "waiting_start_date"
    WAITING_END_DATE = "waiting_end_date"
    WAITING_EVENT_TYPE = "waiting_event_type"
    WAITING_RUNS_PER_WEEK = "waiting_runs_per_week"
    WAITING_REGISTRATION_OPEN = "waiting_registration_open"
    WAITING_ADD_CATEGORY = "waiting_add_category"
    WAITING_CATEGORY_SELECT = "waiting_category_select"
    WAITING_CATEGORY_DISTANCE = "waiting_category_distance"

class RegistrationState(BaseStateGroup):
    WAITING_EVENT = 'wating_event'
    WAITING_CATEGORY = 'waiting_category'


class StatsState(BaseStateGroup):
    WAITING_EVENT = 'waiting_stats_event'


class GeneralReportState(BaseStateGroup):
    WAITING_EVENT = 'waiting_general_report_event'
    WAITING_CATEGORY = 'waiting_general_report_category'


class ReportState(BaseStateGroup):
    WAITING_CHALLENGE = 'waiting_report_challenge'