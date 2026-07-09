from aiogram.fsm.state import StatesGroup, State


class ClientBookingStates(StatesGroup):
    choose_doctor = State()
    choose_day = State()
    choose_slot = State()
    complaint = State()
    confirm = State()
