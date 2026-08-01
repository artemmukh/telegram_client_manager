
from aiogram.fsm.state import StatesGroup, State

class RegisterStates(StatesGroup):
    language = State()
    phone = State()
    name_conflict = State()
    full_name = State()
    birth_date = State()
    gender = State()
    confirm_register = State()
    edit_full_name = State()

