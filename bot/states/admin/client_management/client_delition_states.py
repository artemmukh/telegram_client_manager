from aiogram.fsm.state import State, StatesGroup


class ClientDeletionStates(StatesGroup):

    client_search_variant = State()
    client_deletion_name = State()
    client_deletion_phone = State()
    client_deletion_confirm = State()
