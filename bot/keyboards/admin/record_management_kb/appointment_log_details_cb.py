from aiogram.filters.callback_data import CallbackData


class AppointmentLogDetailsCB(CallbackData, prefix="appointment_log_details"):
    appointment_id: int


class AppointmentLogHideDetailsCB(CallbackData, prefix="appointment_log_hide_details"):
    appointment_id: int
