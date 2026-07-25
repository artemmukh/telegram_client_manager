from aiogram.types import CallbackQuery, FSInputFile

from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.utils.medical_record_enums import MedicalRecordStatus

READY_STATUSES = (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL)


async def deliver_medical_record(
    callback_query: CallbackQuery,
    medical_record_service: MedicalRecordService,
    appointment_scheduler: AppointmentScheduler,
    appointment_id: int,
) -> None:
    """Handle the "Получить историю болезни" button, shared by admin and client.

    Delegates to MedicalRecordService.get_or_generate (see its docstring for the
    three possible outcomes). If the call just created a pending row for an
    appointment that never had generation triggered (edge case), kicks off
    generation via AppointmentScheduler.schedule_medical_record_generation.
    Ready documents are sent to the caller's own chat via answer_document.
    Pending/generating statuses get a polite "check back later" alert.
    A failed status gets a distinct alert instead, since a failed record
    will never become ready on its own (e.g. a clinic instance with no
    configured template always ends up FAILED) and telling the user to
    check back later would be misleading. Callers are responsible for
    verifying the caller owns/may view this appointment before calling
    this helper.
    """
    record, needs_generation = await medical_record_service.get_or_generate(appointment_id)

    if needs_generation:
        await appointment_scheduler.schedule_medical_record_generation(appointment_id)

    if record.status in READY_STATUSES:
        await callback_query.message.answer_document(FSInputFile(record.file_path))
        await callback_query.answer()
    elif record.status is MedicalRecordStatus.FAILED:
        await callback_query.answer(
            "Не удалось подготовить документ, обратитесь к администратору", show_alert=True,
        )
    else:
        await callback_query.answer(
            "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
        )
