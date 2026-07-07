from aiogram.fsm.state import StatesGroup, State


class AppointmentResponseStates(StatesGroup):
    confirm = State()
    cancel = State()
    confirm_cancel = State()
