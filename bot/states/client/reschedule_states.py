from aiogram.fsm.state import StatesGroup, State


class ClientRescheduleStates(StatesGroup):
    choose_day = State()
    choose_slot = State()
    confirm = State()
