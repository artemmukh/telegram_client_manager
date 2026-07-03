from aiogram.fsm.state import State, StatesGroup


class ClientDeletionStates(StatesGroup):

    client_search_variant = State()
    client_search_name = State()
    client_search_phone = State()
    confirm_deletion = State()
    proceed_deletion = State()
    edit_full_name = State()
    edit_phone = State()

