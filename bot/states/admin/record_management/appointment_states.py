from aiogram.fsm.state import StatesGroup, State


class AppointmentCreationStates(StatesGroup):
    choose_doctor = State()
    client_full_name = State()
    client_phone = State()
    confirm_create = State()
    edit_full_name = State()
    edit_phone = State()
    appointment_datetime = State()
    appointment_datetime_confirm = State()
    purpose = State()
    confirm = State()
