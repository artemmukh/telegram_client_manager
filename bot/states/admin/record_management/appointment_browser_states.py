from aiogram.fsm.state import State, StatesGroup


class AppointmentBrowserStates(StatesGroup):

    search_variant = State()
    search_name = State()
    search_phone = State()
    edit_search_full_name = State()
    edit_search_phone = State()
    confirm_search = State()

    new_datetime = State()
    confirm_new_datetime = State()

    new_purpose = State()
    confirm_new_purpose = State()

    confirm_delete = State()
