from aiogram.fsm.state import State, StatesGroup


class SlotBlockCreationStates(StatesGroup):
    choose_target = State()
    range_start = State()
    range_end = State()
    reason = State()
    confirm_conflicts = State()
    confirm_block = State()
