from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.medical_documents_cb import (
    MedicalDocumentActionCB,
    MedicalDocumentAppointmentCB,
    MedicalDocumentListCB,
    MedicalDocumentRecordCB,
)
from bot.models.medical_record import MedicalRecord
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.pagination import get_circular_page

_TEXTS = {
    "ru": {
        "document": "📄 {diagnosis} · {created_at} · {status}",
        "document_with_context": "📄 {diagnosis} · {created_at} · {status}\n🗓 {appointment} · {doctor}",
        "page": "{page} из {total}",
        "generate": "➕ Новая генерация",
        "bulk": "📤 Выдать все документы",
        "download": "📥 Скачать",
        "delete": "🗑️ Удалить",
        "confirm_delete": "✅ Да, удалить",
        "cancel": "❌ Отмена",
        "cancel_generation": "❌ Отменить генерацию",
        "back": "⬅️ Назад",
        "status_pending": "Ожидает",
        "status_generating": "Готовится",
        "status_ready": "Готов",
        "status_ready_partial": "Готов частично",
        "status_failed": "Ошибка",
    },
    "uz": {
        "document": "📄 {diagnosis} · {created_at} · {status}",
        "document_with_context": "📄 {diagnosis} · {created_at} · {status}\n🗓 {appointment} · {doctor}",
        "page": "{page}/{total}",
        "generate": "➕ Yangi yaratish",
        "bulk": "📤 Barcha hujjatlarni yuborish",
        "download": "📥 Yuklab olish",
        "delete": "🗑️ O'chirish",
        "confirm_delete": "✅ Ha, o'chirish",
        "cancel": "❌ Bekor qilish",
        "cancel_generation": "❌ Yaratishni bekor qilish",
        "back": "⬅️ Orqaga",
        "status_pending": "Kutilmoqda",
        "status_generating": "Tayyorlanmoqda",
        "status_ready": "Tayyor",
        "status_ready_partial": "Qisman tayyor",
        "status_failed": "Xato",
    },
}


def _texts(lang: str) -> dict[str, str]:
    return _TEXTS.get(lang, _TEXTS["ru"])


def medical_record_status_label(status: MedicalRecordStatus, lang: str = "ru") -> str:
    """Return the localized short document lifecycle label for admin UI."""
    texts = _texts(lang)
    return texts.get(f"status_{status.value}", status.value)


def _document_button_text(document: MedicalRecord, source: str, texts: dict[str, str]) -> str:
    diagnosis = document.diagnosis or "—"
    created_at = document.created_at or "—"
    status = texts.get(f"status_{document.status.value}", document.status.value)
    if source != "c":
        return texts["document"].format(
            diagnosis=diagnosis,
            created_at=created_at,
            status=status,
        )

    appointment = document.appointment_datetime or "—"
    doctor = document.doctor_full_name or "—"
    return texts["document_with_context"].format(
        diagnosis=diagnosis,
        created_at=created_at,
        status=status,
        appointment=appointment,
        doctor=doctor,
    )


def medical_documents_list_kb(
    documents: list[MedicalRecord],
    *,
    source: str,
    source_id: int,
    page: int,
    total_pages: int,
    back_callback_data: str,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build a paginated admin document list without any access decisions."""
    texts = _texts(lang)
    builder = InlineKeyboardBuilder()
    rows: list[int] = []

    for document in documents:
        if document.id is None:
            continue
        builder.button(
            text=_document_button_text(document, source, texts),
            callback_data=MedicalDocumentRecordCB(
                source=source,
                source_id=source_id,
                record_id=document.id,
            ).pack(),
        )
        rows.append(1)

    if total_pages > 1:
        builder.button(text="⬅️", callback_data=MedicalDocumentListCB(
            source=source, source_id=source_id, page=get_circular_page(page, total_pages, "prev"),
        ).pack())
        builder.button(text=texts["page"].format(page=page, total=total_pages), callback_data="noop")
        builder.button(text="➡️", callback_data=MedicalDocumentListCB(
            source=source, source_id=source_id, page=get_circular_page(page, total_pages, "next"),
        ).pack())
        rows.append(3)
    else:
        builder.button(text=texts["page"].format(page=1, total=1), callback_data="noop")
        rows.append(1)

    if source == "a":
        builder.button(
            text=texts["generate"],
            callback_data=MedicalDocumentAppointmentCB(action="g", appointment_id=source_id).pack(),
        )
        builder.button(
            text=texts["bulk"],
            callback_data=MedicalDocumentAppointmentCB(action="b", appointment_id=source_id).pack(),
        )
        rows.append(1)
        rows.append(1)

    builder.button(text=texts["back"], callback_data=back_callback_data)
    rows.append(1)
    builder.adjust(*rows)
    return builder.as_markup()


def medical_document_detail_kb(
    *,
    source: str,
    source_id: int,
    record_id: int,
    page: int,
    status: MedicalRecordStatus,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    texts = _texts(lang)
    builder = InlineKeyboardBuilder()

    actions = [("delete", texts["delete"])]
    if status in (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL):
        actions.insert(0, ("download", texts["download"]))

    for action, label in actions:
        builder.button(
            text=label,
            callback_data=MedicalDocumentActionCB(
                action=action,
                source=source,
                source_id=source_id,
                record_id=record_id,
            ).pack(),
        )

    builder.button(
        text=texts["back"],
        callback_data=MedicalDocumentListCB(source=source, source_id=source_id, page=page).pack(),
    )
    builder.adjust(len(actions), 1)
    return builder.as_markup()


def medical_document_delete_confirm_kb(
    *,
    source: str,
    source_id: int,
    record_id: int,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    texts = _texts(lang)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts["confirm_delete"],
        callback_data=MedicalDocumentActionCB(
            action="confirm_delete",
            source=source,
            source_id=source_id,
            record_id=record_id,
        ).pack(),
    )
    builder.button(
        text=texts["cancel"],
        callback_data=MedicalDocumentActionCB(
            action="cancel_delete",
            source=source,
            source_id=source_id,
            record_id=record_id,
        ).pack(),
    )
    builder.adjust(1, 1)
    return builder.as_markup()


def medical_document_generation_cancel_kb(
    appointment_id: int,
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Build the FSM cancellation control for temporary-diagnosis entry."""
    texts = _texts(lang)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts["cancel_generation"],
        callback_data=MedicalDocumentAppointmentCB(action="c", appointment_id=appointment_id).pack(),
    )
    return builder.as_markup()
