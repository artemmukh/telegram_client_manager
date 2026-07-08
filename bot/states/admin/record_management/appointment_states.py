from aiogram.fsm.state import StatesGroup, State


class AppointmentCreationStates(StatesGroup):
    client_full_name = State()
    client_phone = State()
    confirm_create = State()
    edit_full_name = State()
    edit_phone = State()
    appointment_datetime = State()
    appointment_datetime_confirm = State()
    purpose = State()
    confirm = State()


class AppointmentSearchStates(StatesGroup):
    appointment_search_variant = State()  # Выбор способа поиска
    appointment_search_name = State()     # Ввод ФИО
    appointment_search_phone = State()    # Ввод телефона
    confirm_search = State()              # Подтверждение перед поиском
    edit_full_name = State()              # Редактирование ФИО
    edit_phone = State()                  # Редактирование телефона


class AppointmentDeletionStates(StatesGroup):
    client_phone = State()
    proceed = State()


class AppointmentUpdateStates(StatesGroup):
    client_phone = State()
    proceed = State()
    new_datetime = State()
    new_purpose = State()
