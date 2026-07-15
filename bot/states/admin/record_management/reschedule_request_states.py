from aiogram.fsm.state import State, StatesGroup


class RescheduleRequestStates(StatesGroup):

    new_datetime = State()
    confirm_new_datetime = State()
