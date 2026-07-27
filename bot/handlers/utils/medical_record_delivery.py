from aiogram.types import CallbackQuery, FSInputFile

from bot.models.medical_record import MedicalRecord
from bot.services.medical_record.medical_record_management import READY_STATUSES, MedicalRecordService
from bot.utils.medical_record_enums import MedicalRecordStatus

FAILURE_MESSAGE = "Не удалось подготовить документ, обратитесь к администратору"


async def deliver_medical_record(
    callback_query: CallbackQuery,
    medical_record_service: MedicalRecordService,
    appointment_id: int,
) -> None:
    """Handle the "Получить историю болезни" button, shared by admin and client.

    Sends every already-generated ready document for this appointment (one
    message per diagnosis, since a changed diagnosis produces its own
    document instead of overwriting the previous one). If none exist yet,
    generation is awaited synchronously right here instead of dispatching a
    background job, so the button press either sends a document or reports
    a concrete failure — no more "check back later" polling.

    A document whose file went missing from disk is regenerated in place
    (only that one record, keyed by its own diagnosis) before being sent,
    instead of failing the whole batch.

    Generation can take several seconds (LLM call + docx render), well past
    Telegram's ~15s callback-query answer window, so callback_query.answer()
    is always called up front; any follow-up user-facing text after an
    await is sent as a plain chat message instead of a callback alert.

    Callers are responsible for verifying the caller owns/may view this
    appointment before calling this helper.
    """
    documents = await medical_record_service.get_ready_documents(appointment_id)

    if documents:
        await callback_query.answer()
        for record in documents:
            sent = await _send_document(callback_query, medical_record_service, record)
            if not sent:
                await callback_query.message.answer(FAILURE_MESSAGE)
        return

    await callback_query.answer("Готовим документ, это может занять до минуты", show_alert=True)

    record = await medical_record_service.generate(appointment_id)

    if record is None or record.status is MedicalRecordStatus.FAILED:
        await callback_query.message.answer(FAILURE_MESSAGE)
        return

    if record.status not in READY_STATUSES:
        await callback_query.message.answer("Документ ещё готовится, попробуйте через пару минут")
        return

    await callback_query.message.answer_document(FSInputFile(record.file_path))


async def add_medical_record_document(
    callback_query: CallbackQuery,
    medical_record_service: MedicalRecordService,
    appointment_id: int,
    diagnosis: str | None,
) -> None:
    """Handle the "Добавить документ" button, shared by admin and client.

    Explicitly generates a document for the appointment's CURRENT diagnosis,
    unlike deliver_medical_record which only sends what already exists (or
    generates once if nothing exists yet). Idempotent per (appointment_id,
    diagnosis): if a document for this exact diagnosis already exists, the
    service returns it instead of creating a duplicate; if the diagnosis
    differs from every existing record, a genuinely new document is created.

    Generation can take several seconds (LLM call + docx render), well past
    Telegram's ~15s callback-query answer window, so callback_query.answer()
    is always called up front; any follow-up user-facing text after an
    await is sent as a plain chat message instead of a callback alert.

    Callers are responsible for verifying the caller owns/may view this
    appointment before calling this helper.
    """
    await callback_query.answer("Готовим документ, это может занять до минуты", show_alert=True)

    record = await medical_record_service.generate(appointment_id, diagnosis)

    if record is None or record.status is MedicalRecordStatus.FAILED:
        await callback_query.message.answer(FAILURE_MESSAGE)
        return

    if record.status not in READY_STATUSES:
        await callback_query.message.answer("Документ ещё готовится, попробуйте через пару минут")
        return

    if not await _send_document(callback_query, medical_record_service, record):
        await callback_query.message.answer(FAILURE_MESSAGE)


async def _send_document(
    callback_query: CallbackQuery,
    medical_record_service: MedicalRecordService,
    record: MedicalRecord,
) -> bool:
    """Send a record's file, regenerating it first if missing from disk.

    Returns whether a document was actually sent.
    """
    resolved = await medical_record_service.ensure_file_exists(record)
    if resolved is None:
        return False

    await callback_query.message.answer_document(FSInputFile(resolved.file_path))
    return True
