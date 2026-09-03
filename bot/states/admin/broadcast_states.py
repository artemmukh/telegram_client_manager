from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    edit_text = State()
    confirm_send = State()
