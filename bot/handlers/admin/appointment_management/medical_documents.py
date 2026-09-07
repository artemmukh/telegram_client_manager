from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.exceptions.medical_record_exceptions import MedicalRecordDeletionError
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.medical_record_delivery import (
    deliver_ready_medical_records,
    deliver_selected_medical_record,
)
from bot.keyboards.admin.client_management_kb.client_browser_cb import (
    ClientActionCB,
    ClientCardCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCardCB,
)
from bot.keyboards.admin.record_management_kb.medical_documents_cb import (
    MedicalDocumentActionCB,
    MedicalDocumentAppointmentCB,
    MedicalDocumentListCB,
    MedicalDocumentRecordCB,
)
from bot.keyboards.admin.record_management_kb.medical_documents_kb import (
    medical_document_delete_confirm_kb,
    medical_document_detail_kb,
    medical_document_generation_cancel_kb,
    medical_documents_list_kb,
    medical_record_status_label,
)
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.client.client_management import ClientManagement
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.states.admin.record_management.medical_documents_states import (
    MedicalDocumentStates,
)
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import RoleFilter
from bot.validators.validators import validate_purpose

_TEXTS = {
    "ru": {
        "appointment_title": "📄 Документы записи №{appointment_id}",
        "client_title": "📄 Документы клиента: {client_name}",
        "empty": "Документов пока нет.",
        "detail": "📄 Документ\n\nДиагноз: {diagnosis}\nСтатус: {status}\nСоздан: {created_at}",
        "not_available": "Документ или запись больше недоступны.",
        "download_not_ready": "Документ ещё не готов к скачиванию.",
        "appointment_not_available": "Запись больше недоступна.",
        "client_not_available": "Клиент больше недоступен.",
        "delete_prompt": "Удалить этот документ? Файл будет удалён с сервера клиники.",
        "deleted": "Документ удалён.",
        "delete_error": "Не удалось удалить документ. Попробуйте ещё раз.",
        "enter_diagnosis": "Введите временный диагноз для нового документа:",
        "generation_failed": "Не удалось подготовить документ.",
        "generating": "Готовим документ, это может занять до минуты.",
    },
    "uz": {
        "appointment_title": "📄 Yozuv №{appointment_id} hujjatlari",
        "client_title": "📄 Mijoz hujjatlari: {client_name}",
        "empty": "Hali hujjatlar yo'q.",
        "detail": "📄 Hujjat\n\nTashxis: {diagnosis}\nHolat: {status}\nYaratilgan: {created_at}",
        "not_available": "Hujjat yoki yozuv endi mavjud emas.",
        "download_not_ready": "Hujjat hali yuklab olishga tayyor emas.",
        "appointment_not_available": "Yozuv endi mavjud emas.",
        "client_not_available": "Mijoz endi mavjud emas.",
        "delete_prompt": "Bu hujjat o'chirilsinmi? Fayl klinika serveridan o'chiriladi.",
        "deleted": "Hujjat o'chirildi.",
        "delete_error": "Hujjatni o'chirib bo'lmadi. Qayta urinib ko'ring.",
        "enter_diagnosis": "Yangi hujjat uchun vaqtinchalik tashxisni kiriting:",
        "generation_failed": "Hujjatni tayyorlab bo'lmadi.",
        "generating": "Hujjat tayyorlanmoqda, bu bir daqiqacha vaqt olishi mumkin.",
    },
}


def _texts(lang: str) -> dict[str, str]:
    return _TEXTS.get(lang, _TEXTS["ru"])


def _document_detail_text(document: MedicalRecord, lang: str) -> str:
    texts = _texts(lang)
    return texts["detail"].format(
        diagnosis=escape(document.diagnosis or "—"),
        status=escape(medical_record_status_label(document.status, lang)),
        created_at=escape(document.created_at or "—"),
    )


def _list_text(source: str, source_id: int, documents: list[MedicalRecord], client: User | None, lang: str) -> str:
    texts = _texts(lang)
    if source == "a":
        title = texts["appointment_title"].format(appointment_id=source_id)
    else:
        title = texts["client_title"].format(client_name=escape(client.full_name if client else "—"))
    return f"{title}\n\n{texts['empty']}" if not documents else title


def create_admin_medical_documents_router(
    medical_record_service: MedicalRecordService,
    appointment_management: AppointmentManagement,
    client_management: ClientManagement,
) -> Router:
    """Administrative entry points and FSM for multi-document management.

    The router is deliberately limited to Telegram/FSM work. Document access,
    pagination, physical file deletion, and generation remain in services.
    """
    router = Router()
    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def _authorized_appointment_for_admin(appointment_id: int, telegram_id: int) -> Appointment | None:
        return await appointment_management.get_appointment_for_admin(appointment_id, telegram_id)

    async def _completed_appointment_for_admin(appointment_id: int, telegram_id: int) -> Appointment | None:
        appointment = await _authorized_appointment_for_admin(appointment_id, telegram_id)
        if appointment is None or appointment.status is not AppointmentStatus.COMPLETED:
            return None
        return appointment

    async def _client_scope(client_id: int, telegram_id: int) -> tuple[User | None, int, int | None]:
        clinic_id, doctor_id = await appointment_management.resolve_admin_appointment_filter(telegram_id)
        client = await client_management.get_client_by_id(client_id, clinic_id)
        return client, clinic_id, doctor_id

    async def _document_in_scope(
        callback_data: MedicalDocumentRecordCB | MedicalDocumentActionCB,
        telegram_id: int,
    ) -> tuple[MedicalRecord, Appointment] | None:
        document = await medical_record_service.get_document_by_id(callback_data.record_id)
        if document is None:
            return None

        appointment = await _authorized_appointment_for_admin(document.appointment_id, telegram_id)
        if appointment is None:
            return None

        if callback_data.source == "c":
            if appointment.client_id != callback_data.source_id:
                return None
            client, _, _ = await _client_scope(callback_data.source_id, telegram_id)
            if client is None:
                return None
        elif (
            callback_data.source != "a"
            or callback_data.source_id != appointment.id
            or appointment.status is not AppointmentStatus.COMPLETED
        ):
            return None

        return document, appointment

    async def _current_document_page(state: FSMContext) -> int:
        page = (await state.get_data()).get("document_page", 1)
        return page if isinstance(page, int) and page > 0 else 1

    async def _back_callback_data(source: str, source_id: int, state: FSMContext) -> str:
        data = await state.get_data()
        if source == "a":
            return ApptCardCB(
                appointment_id=source_id,
                mode=data.get("document_return_mode", "list"),
                page=data.get("document_return_page", 1),
                tab=data.get("document_return_tab", ""),
            ).pack()
        return ClientCardCB(
            client_id=source_id,
            mode=data.get("document_return_mode", "list"),
            page=data.get("document_return_page", 1),
        ).pack()

    async def _render_list(
        callback_query: CallbackQuery,
        state: FSMContext,
        *,
        source: str,
        source_id: int,
        page: int,
        current_user: User,
        callback_answer_text: str | None = None,
        reset_generation_state: bool = True,
    ) -> bool:
        lang = current_user.language
        client: User | None = None
        if source == "a":
            appointment = await _completed_appointment_for_admin(source_id, callback_query.from_user.id)
            if appointment is None:
                await callback_query.answer(_texts(lang)["appointment_not_available"], show_alert=True)
                return False
            result = await medical_record_service.paginate_appointment_documents(source_id, page)
        elif source == "c":
            client, clinic_id, doctor_id = await _client_scope(source_id, callback_query.from_user.id)
            if client is None:
                await callback_query.answer(_texts(lang)["client_not_available"], show_alert=True)
                return False
            result = await medical_record_service.paginate_client_documents(
                source_id, clinic_id, doctor_id, page,
            )
        else:
            await callback_query.answer(_texts(lang)["not_available"], show_alert=True)
            return False

        if reset_generation_state:
            await state.set_state(None)
            await state.update_data(document_generation_appointment_id=None)
        await state.update_data(
            document_source=source,
            document_source_id=source_id,
            document_page=result.current_page,
        )
        if callback_answer_text is None:
            await callback_query.answer()
        else:
            await callback_query.answer(callback_answer_text)
        await callback_query.message.edit_text(
            _list_text(source, source_id, result.items, client, lang),
            reply_markup=medical_documents_list_kb(
                result.items,
                source=source,
                source_id=source_id,
                page=result.current_page,
                total_pages=result.total_pages,
                back_callback_data=await _back_callback_data(source, source_id, state),
                lang=lang,
            ),
        )
        await remember_tracked_message(state, callback_query.message)
        return True

    @router.callback_query(ApptActionCB.filter(F.action == "documents"))
    async def open_appointment_documents(
        callback_query: CallbackQuery,
        callback_data: ApptActionCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await state.update_data(
            document_return_mode=callback_data.mode,
            document_return_page=callback_data.page,
            document_return_tab=callback_data.value,
        )
        await _render_list(
            callback_query,
            state,
            source="a",
            source_id=callback_data.appointment_id,
            page=1,
            current_user=current_user,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "documents"))
    async def open_client_documents(
        callback_query: CallbackQuery,
        callback_data: ClientActionCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await state.update_data(
            document_return_mode=callback_data.mode,
            document_return_page=callback_data.page,
            document_return_tab="",
        )
        await _render_list(
            callback_query,
            state,
            source="c",
            source_id=callback_data.client_id,
            page=1,
            current_user=current_user,
        )

    @router.callback_query(MedicalDocumentListCB.filter())
    async def paginate_documents(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentListCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await _render_list(
            callback_query,
            state,
            source=callback_data.source,
            source_id=callback_data.source_id,
            page=callback_data.page,
            current_user=current_user,
        )

    @router.callback_query(MedicalDocumentRecordCB.filter())
    async def open_document_detail(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentRecordCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        scoped = await _document_in_scope(callback_data, callback_query.from_user.id)
        lang = current_user.language
        if scoped is None:
            await callback_query.answer(_texts(lang)["not_available"], show_alert=True)
            return

        document, _ = scoped
        page = await _current_document_page(state)
        await state.set_state(None)
        await state.update_data(document_generation_appointment_id=None)
        await callback_query.answer()
        await callback_query.message.edit_text(
            _document_detail_text(document, lang),
            reply_markup=medical_document_detail_kb(
                source=callback_data.source,
                source_id=callback_data.source_id,
                record_id=callback_data.record_id,
                page=page,
                status=document.status,
                lang=lang,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(MedicalDocumentActionCB.filter(F.action == "download"))
    async def download_document(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentActionCB,
        current_user: User,
    ) -> None:
        scoped = await _document_in_scope(callback_data, callback_query.from_user.id)
        if scoped is None:
            await callback_query.answer(_texts(current_user.language)["not_available"], show_alert=True)
            return
        document, appointment = scoped
        if document.status not in (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL):
            await callback_query.answer(_texts(current_user.language)["download_not_ready"], show_alert=True)
            return
        await deliver_selected_medical_record(
            callback_query,
            medical_record_service,
            callback_data.record_id,
            appointment.id,
            lang=current_user.language,
        )

    @router.callback_query(MedicalDocumentActionCB.filter(F.action == "delete"))
    async def request_delete_document(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentActionCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if await _document_in_scope(callback_data, callback_query.from_user.id) is None:
            await callback_query.answer(_texts(current_user.language)["not_available"], show_alert=True)
            return
        await state.set_state(None)
        await state.update_data(document_generation_appointment_id=None)
        await callback_query.answer()
        await callback_query.message.edit_text(
            _texts(current_user.language)["delete_prompt"],
            reply_markup=medical_document_delete_confirm_kb(
                source=callback_data.source,
                source_id=callback_data.source_id,
                record_id=callback_data.record_id,
                lang=current_user.language,
            ),
        )

    @router.callback_query(MedicalDocumentActionCB.filter(F.action == "cancel_delete"))
    async def cancel_delete_document(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentActionCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await open_document_detail(
            callback_query,
            MedicalDocumentRecordCB(
                source=callback_data.source,
                source_id=callback_data.source_id,
                record_id=callback_data.record_id,
            ),
            state,
            current_user,
        )

    @router.callback_query(MedicalDocumentActionCB.filter(F.action == "confirm_delete"))
    async def confirm_delete_document(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentActionCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        lang = current_user.language
        scoped = await _document_in_scope(callback_data, callback_query.from_user.id)
        if scoped is None:
            await callback_query.answer(_texts(lang)["not_available"], show_alert=True)
            return
        _, appointment = scoped
        try:
            deleted = await medical_record_service.delete_document(
                callback_data.record_id,
                appointment.id,
            )
        except MedicalRecordDeletionError:
            await callback_query.answer(_texts(lang)["delete_error"], show_alert=True)
            return
        if not deleted:
            await callback_query.answer(_texts(lang)["not_available"], show_alert=True)
            return
        await _render_list(
            callback_query,
            state,
            source=callback_data.source,
            source_id=callback_data.source_id,
            page=await _current_document_page(state),
            current_user=current_user,
            callback_answer_text=_texts(lang)["deleted"],
        )

    @router.callback_query(MedicalDocumentAppointmentCB.filter(F.action == "b"))
    async def deliver_all_documents(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentAppointmentCB,
        current_user: User,
    ) -> None:
        if await _completed_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id) is None:
            await callback_query.answer(_texts(current_user.language)["appointment_not_available"], show_alert=True)
            return
        await deliver_ready_medical_records(
            callback_query,
            medical_record_service,
            callback_data.appointment_id,
            lang=current_user.language,
        )

    @router.callback_query(MedicalDocumentAppointmentCB.filter(F.action == "g"))
    async def request_document_generation(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentAppointmentCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        lang = current_user.language
        if await _completed_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id) is None:
            await callback_query.answer(_texts(lang)["appointment_not_available"], show_alert=True)
            return
        await state.update_data(document_generation_appointment_id=callback_data.appointment_id)
        await state.set_state(MedicalDocumentStates.diagnosis)
        await callback_query.answer()
        await callback_query.message.edit_text(
            _texts(lang)["enter_diagnosis"],
            reply_markup=medical_document_generation_cancel_kb(callback_data.appointment_id, lang=lang),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(MedicalDocumentAppointmentCB.filter(F.action == "c"))
    async def cancel_document_generation(
        callback_query: CallbackQuery,
        callback_data: MedicalDocumentAppointmentCB,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await state.set_state(None)
        await state.update_data(document_generation_appointment_id=None)
        if await _completed_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id) is None:
            await callback_query.answer(_texts(current_user.language)["appointment_not_available"], show_alert=True)
            return
        await _render_list(
            callback_query,
            state,
            source="a",
            source_id=callback_data.appointment_id,
            page=await _current_document_page(state),
            current_user=current_user,
            reset_generation_state=False,
        )

    @router.message(MedicalDocumentStates.diagnosis, F.text)
    async def generate_document_from_diagnosis(message: Message, state: FSMContext, current_user: User) -> None:
        lang = current_user.language
        try:
            diagnosis = validate_purpose(message.text.strip())
        except ValidationError as exc:
            await message.answer(exc.localized(lang))
            return

        data = await state.get_data()
        appointment_id = data.get("document_generation_appointment_id")
        if not isinstance(appointment_id, int) or await _completed_appointment_for_admin(appointment_id, message.from_user.id) is None:
            await message.answer(_texts(lang)["appointment_not_available"])
            await state.set_state(None)
            return

        await message.answer(_texts(lang)["generating"])
        document = await medical_record_service.generate(appointment_id, diagnosis)
        await state.set_state(None)
        if document is None or document.status not in (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL):
            await message.answer(_texts(lang)["generation_failed"])
            return

        current_document = await medical_record_service.ensure_file_exists(document)
        if current_document is None or not current_document.file_path:
            await message.answer(_texts(lang)["generation_failed"])
            return
        await message.answer_document(FSInputFile(current_document.file_path))

        result = await medical_record_service.paginate_appointment_documents(
            appointment_id,
            data.get("document_page", 1),
        )
        await edit_tracked_message(
            message.bot,
            state,
            _list_text("a", appointment_id, result.items, None, lang),
            reply_markup=medical_documents_list_kb(
                result.items,
                source="a",
                source_id=appointment_id,
                page=result.current_page,
                total_pages=result.total_pages,
                back_callback_data=await _back_callback_data("a", appointment_id, state),
                lang=lang,
            ),
        )

    return router
