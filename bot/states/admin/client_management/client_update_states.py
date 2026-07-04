from aiogram.fsm.state import State, StatesGroup


class ClientUpdateStates(StatesGroup):

    client_search_name = State()
    client_search_phone = State()
    confirm_search = State()
    edit_full_name = State()
    edit_phone = State()

    proceed_update = State()

    new_full_name = State()
    confirm_new_full_name = State()

    new_phone = State()
    confirm_new_phone = State()
