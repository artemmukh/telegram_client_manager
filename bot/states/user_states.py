
from aiogram.fsm.state import StatesGroup, State

class RegisterStates(StatesGroup):
    full_name = State()
    phone = State()

class ClientStates(StatesGroup):
    client_full_name = State()
    client_phone = State()

    confirm_create = State()

    client_edit_full_name = State()
    client_edit_phone = State()

