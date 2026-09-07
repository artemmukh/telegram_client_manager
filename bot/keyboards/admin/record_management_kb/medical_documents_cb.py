from aiogram.filters.callback_data import CallbackData


class MedicalDocumentListCB(CallbackData, prefix="mdl"):
    """Open a particular page of an administrative document list."""

    source: str
    source_id: int
    page: int


class MedicalDocumentRecordCB(CallbackData, prefix="mdr"):
    """Open one document card while retaining the parent list context."""

    source: str
    source_id: int
    record_id: int


class MedicalDocumentActionCB(CallbackData, prefix="mda"):
    """Download or request deletion of one document."""

    action: str
    source: str
    source_id: int
    record_id: int


class MedicalDocumentAppointmentCB(CallbackData, prefix="mdp"):
    """Actions available only from an appointment-scoped document list."""

    action: str
    appointment_id: int
