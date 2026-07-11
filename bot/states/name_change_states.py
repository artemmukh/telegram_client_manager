
from aiogram.fsm.state import StatesGroup, State

class NameChangeStates(StatesGroup):
    entering_name = State()
