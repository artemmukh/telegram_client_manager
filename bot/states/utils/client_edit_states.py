from aiogram.fsm.state import StatesGroup, State


class EditStates(StatesGroup):

    edit_full_name = State()
    edit_phone = State()
