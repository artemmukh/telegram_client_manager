from aiogram.fsm.state import StatesGroup, State


class AppointmentResponseStates(StatesGroup):
    confirm_cancel = State()
