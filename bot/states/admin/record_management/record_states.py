from aiogram.fsm.state import StatesGroup, State


class RecordStates(StatesGroup):
    record_name = State()
    record_phone = State()
    record_date = State()
    record_description = State()