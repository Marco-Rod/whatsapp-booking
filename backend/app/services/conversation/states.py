from enum import Enum


class ConversationState(str, Enum):
    MAIN_MENU = "main_menu"
    SELECT_SERVICE = "select_service"
    SELECT_DATE = "select_date"
    SELECT_TIME = "select_time"
    CONFIRM_APPOINTMENT = "confirm_appointment"
