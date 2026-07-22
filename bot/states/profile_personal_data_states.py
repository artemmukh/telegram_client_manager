from aiogram.fsm.state import StatesGroup, State

class ProfilePersonalDataStates(StatesGroup):
    birth_date = State()
    gender = State()
