from aiogram.filters.callback_data import CallbackData


class AppointmentInviteActionCB(CallbackData, prefix="appt_invite_act"):
    """Действие клиента над первоначальным приглашением от админа: confirm, cancel."""
    action: str
    appointment_id: int
