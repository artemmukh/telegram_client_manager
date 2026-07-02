from aiogram.fsm.state import State, StatesGroup


class ClientSearchStates(StatesGroup):

    client_search_variant = State()
    client_search_name = State()
    client_search_phone = State()
    confirm_search = State()
    edit_full_name = State()
    edit_phone = State()
