
from aiogram.fsm.state import StatesGroup, State

class RegisterStates(StatesGroup):
    user_full_name = State()
    user_phone = State()

class ClientStates(StatesGroup):
    client_name = State()
    client_phone = State()

class RecordStates(StatesGroup):
    record_name = State()
    record_phone = State()
    record_date = State()
    record_description = State()