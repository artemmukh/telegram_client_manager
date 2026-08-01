from aiogram.fsm.state import State, StatesGroup


class BookingNegotiationStates(StatesGroup):
    propose_datetime = State()
    confirm_propose_datetime = State()
    choose_day = State()
    choose_slot = State()
