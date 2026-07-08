from aiogram.fsm.state import State, StatesGroup


class ClientBrowserStates(StatesGroup):

    search_variant = State()
    search_name = State()
    search_phone = State()
    edit_search_full_name = State()
    edit_search_phone = State()
    confirm_search = State()

    new_full_name = State()
    confirm_new_full_name = State()

    new_phone = State()
    confirm_new_phone = State()

    confirm_delete = State()
