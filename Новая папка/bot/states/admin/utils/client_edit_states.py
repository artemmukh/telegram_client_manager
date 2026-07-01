from aiogram.fsm.state import StatesGroup, State


class ClientEditStates(StatesGroup):

    client_edit_full_name = State()
    client_edit_phone = State()
