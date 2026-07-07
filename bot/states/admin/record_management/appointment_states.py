from aiogram.fsm.state import StatesGroup, State


class AppointmentCreationStates(StatesGroup):
    client_name = State()
    client_phone = State()
    client_creation_confirm = State()
    appointment_datetime = State()
    appointment_datetime_confirm = State()
    purpose = State()
    confirm = State()


class AppointmentSearchStates(StatesGroup):
    client_phone = State()


class AppointmentDeletionStates(StatesGroup):
    client_phone = State()
    proceed = State()


class AppointmentUpdateStates(StatesGroup):
    client_phone = State()
    proceed = State()
    new_datetime = State()
    new_purpose = State()
