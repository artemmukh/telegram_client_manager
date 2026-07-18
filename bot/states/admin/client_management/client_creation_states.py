
from aiogram.fsm.state import StatesGroup, State


class ClientCreationStates(StatesGroup):
    client_full_name = State()
    client_phone = State()
    confirm_create = State()
    edit_full_name = State()
    edit_phone = State()
    confirm_duplicate_name = State()

