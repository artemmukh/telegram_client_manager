from aiogram.fsm.state import State, StatesGroup


class AppointmentBrowserStates(StatesGroup):

    search_variant = State()
    search_name = State()
    search_phone = State()
    edit_search_full_name = State()
    edit_search_phone = State()
    confirm_search = State()
    pick_doctor_filter = State()

    new_datetime = State()
    confirm_new_datetime = State()

    new_purpose = State()
    confirm_new_purpose = State()

    new_price = State()
    confirm_new_price = State()

    confirm_delete = State()

    calendar_month = State()
    calendar_day = State()
