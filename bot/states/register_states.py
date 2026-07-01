
from aiogram.fsm.state import StatesGroup, State

class RegisterStates(StatesGroup):
    full_name = State()
    phone = State()
    confirm_register = State()

