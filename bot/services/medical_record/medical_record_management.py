import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path

from bot.config.clinic_instances import MEDICAL_RECORD_TEMPLATE_BY_INSTANCE
from bot.exceptions.medical_record_exceptions import (
    MedicalRecordDeletionError,
    MedicalRecordGenerationError,
)
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.repositories.medical_record_repository import MedicalRecordRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.document_generator.pydocx import OUTPUT_DIR, create_docx
from bot.services.llm.agent import ChatLLM
from bot.services.utils.date_parser import (
    format_appointment_card_datetime,
    get_current_tashkent_datetime,
    get_current_tashkent_time,
)
from bot.utils import prompt_builder
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.pagination import MEDICAL_RECORDS_PER_PAGE

logger = logging.getLogger(__name__)

GENDER_LABELS = {"male": "Мужской", "female": "Женский"}

READY_STATUSES = (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL)

ALREADY_GENERATED_STATUSES = (*READY_STATUSES, MedicalRecordStatus.GENERATING)

DIAGNOSIS_SEGMENT_MAX_LENGTH = 30
PATH_SEGMENT_MAX_LENGTH = 30
STALE_GENERATING_MINUTES = 5

_UNSAFE_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*]')

_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class MedicalRecordPaginationResult:
    """Страница документов истории болезни с метаданными навигации."""

    items: list[MedicalRecord]
    current_page: int
    total_pages: int
    total_count: int


def _sanitize_path_segment(value: str, max_length: int | None = None) -> str:
    """Make a string safe to use as a single filesystem path segment.

    Replaces filesystem-unsafe characters and strips trailing dots/spaces
    (both illegal at the end of a Windows path segment), guards against
    Windows reserved device names, and optionally truncates. Cyrillic and
    other non-ASCII text is preserved as-is.
    """
    sanitized = _UNSAFE_PATH_CHARS_RE.sub("_", value).strip(". ")

    if not sanitized:
        sanitized = "_"

    if sanitized.upper() in _WINDOWS_RESERVED_NAMES:
        sanitized = f"{sanitized}_"

    if max_length is not None and len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip(". ")

    return sanitized


class MedicalRecordService:
    """Orchestrates medical record (.docx) generation for completed appointments.

    Never imports or references Telegram objects. Callers (handlers/jobs) are
    responsible for delivering the resulting file to the user.
    """

    def __init__(
        self,
        medical_record_repository: MedicalRecordRepository,
        appointment_management: AppointmentManagement,
        chat_llm: ChatLLM,
        instance: str,
    ):
        self.medical_record_repository = medical_record_repository
        self.appointment_management = appointment_management
        self.chat_llm = chat_llm
        self.instance = instance
        # A deletion must be able to win over an already-running LLM/render
        # operation without waiting for that operation to finish.  IDs are
        # deliberately used instead of (appointment, diagnosis), so a later
        # explicit generation for the same diagnosis is a new lifecycle.
        self._generating_record_ids: set[int] = set()
        self._cancelled_generation_ids: set[int] = set()
        self._document_locks: dict[int, asyncio.Lock] = {}

    async def generate(
        self,
        appointment_id: int,
        diagnosis: str | None = None,
        *,
        expected_record_id: int | None = None,
    ) -> MedicalRecord | None:
        """Generate the medical record docx for a given diagnosis.

        Keyed by (appointment_id, diagnosis): idempotent for the same
        diagnosis (a record already ready/ready_partial/generating is
        returned unchanged, no new file or row), but a changed diagnosis
        (appointment.purpose edited since the last generation) always gets
        its own new record and document instead of overwriting the old one.

        `diagnosis` defaults to the appointment's current purpose. Callers
        regenerating a specific existing record (e.g. its file went missing
        from disk) must pass that record's own diagnosis explicitly, so the
        appointment's purpose having since changed can't redirect the
        regeneration onto a different record.

        If the appointment or its client cannot be found, no record is
        created/touched and None is returned.

        On LLM failure (after ChatLLM's own retries are exhausted), no
        document is generated and the record is marked failed. Existing
        ready_partial records remain readable for backwards compatibility.
        """
        appointment = await self.appointment_management.get_appointment_by_id(appointment_id)
        if appointment is None:
            logger.warning("Medical record generation: appointment %s not found", appointment_id)
            return None

        if diagnosis is None:
            diagnosis = appointment.purpose
        diagnosis = diagnosis or ""

        existing = await self.medical_record_repository.get_by_appointment_and_diagnosis(appointment_id, diagnosis)
        if expected_record_id is not None and (
            existing is None or existing.id != expected_record_id
        ):
            return None

        if existing is not None and existing.status in ALREADY_GENERATED_STATUSES:
            stale_generating = (
                existing.status is MedicalRecordStatus.GENERATING and self._is_stale_generating(existing)
            )
            if not stale_generating:
                return existing

        record = existing or await self.medical_record_repository.create_pending(
            appointment_id, diagnosis, get_current_tashkent_time(),
        )
        if record.id is None:
            logger.error("Medical record generation: pending record without id for appointment %s", appointment_id)
            return None

        self._generating_record_ids.add(record.id)
        try:
            await self.medical_record_repository.mark_generating(record.id, get_current_tashkent_time())
            if await self._generation_was_deleted(record.id):
                return None

            client = await self.appointment_management.get_client_by_id(appointment.client_id)
            if client is None:
                await self._mark_failed_if_current(record.id, "Клиент не найден.")
                return None

            template_path = MEDICAL_RECORD_TEMPLATE_BY_INSTANCE.get(self.instance)
            if template_path is None:
                logger.info(
                    "Шаблон истории болезни не настроен для инстанса %s, генерация пропущена (appointment %s).",
                    self.instance, appointment_id,
                )
                await self._mark_failed_if_current(
                    record.id, "Шаблон истории болезни не настроен для этой клиники.",
                )
                return None

            try:
                ai_fields, partial = await self._generate_ai_fields(diagnosis, client)
            except MedicalRecordGenerationError as exc:
                logger.warning("LLM generation failed, medical record was not created: %s", exc)
                await self._mark_failed_if_current(record.id, str(exc))
                return None

            tooth_map = ai_fields.pop("tooth_map")

            data = {
                "appointment_date": format_appointment_card_datetime(appointment.datetime),
                "full_name": client.full_name,
                "gender": GENDER_LABELS.get(client.gender, ""),
                "birth_date": self._format_birth_date(client.birth_date),
                "phone": client.phone,
                "diagnosis": diagnosis,
                **ai_fields,
            }

            output_path = self._build_output_path(appointment, client, diagnosis, record.id)

            try:
                file_path = await create_docx(data, tooth_map, output_path, template_path)
            except Exception as exc:
                logger.exception("Failed to render medical record docx for appointment %s", appointment_id)
                await self._mark_failed_if_current(record.id, str(exc))
                return None

            # Keep the short publish step atomic with delete_document.  The
            # LLM/render operation deliberately remains outside this lock, so
            # a user can still delete a long-running generation immediately.
            async with self._document_lock(record.id):
                if await self._generation_was_deleted(record.id):
                    self._remove_rendered_file(file_path)
                    return None

                await self.medical_record_repository.mark_ready(
                    record.id, file_path, partial=partial, updated_at=get_current_tashkent_time(),
                )
                result = await self.medical_record_repository.get_by_appointment_and_diagnosis(
                    appointment_id, diagnosis,
                )
                if result is None:
                    self._remove_rendered_file(file_path)
                return result
        finally:
            self._generating_record_ids.discard(record.id)
            self._cancelled_generation_ids.discard(record.id)

    async def get_ready_documents(self, appointment_id: int) -> list[MedicalRecord]:
        """Return every already-generated, ready document for an appointment."""
        return await self.medical_record_repository.list_ready_by_appointment_id(appointment_id)

    async def paginate_appointment_documents(
        self,
        appointment_id: int,
        page: int,
    ) -> MedicalRecordPaginationResult:
        """Return one page of every document linked to an appointment."""
        total_count = await self.medical_record_repository.count_by_appointment_id(appointment_id)
        current_page, total_pages = self._paginate_math(total_count, page)
        items = await self.medical_record_repository.list_by_appointment_id(
            appointment_id,
            limit=MEDICAL_RECORDS_PER_PAGE,
            offset=(current_page - 1) * MEDICAL_RECORDS_PER_PAGE,
        )

        return MedicalRecordPaginationResult(
            items=items,
            current_page=current_page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def paginate_client_documents(
        self,
        client_id: int,
        clinic_id: int,
        doctor_id: int | None,
        page: int,
    ) -> MedicalRecordPaginationResult:
        """Return a clinic- and doctor-scoped page of a client's documents."""
        total_count = await self.medical_record_repository.count_by_client_id(
            client_id,
            clinic_id,
            doctor_id=doctor_id,
        )
        current_page, total_pages = self._paginate_math(total_count, page)
        items = await self.medical_record_repository.list_by_client_id(
            client_id,
            clinic_id,
            doctor_id=doctor_id,
            limit=MEDICAL_RECORDS_PER_PAGE,
            offset=(current_page - 1) * MEDICAL_RECORDS_PER_PAGE,
        )

        return MedicalRecordPaginationResult(
            items=items,
            current_page=current_page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def get_document_for_appointment(
        self,
        record_id: int,
        appointment_id: int,
    ) -> MedicalRecord | None:
        """Return a document only when it still belongs to the appointment."""
        record = await self.medical_record_repository.get_by_id(record_id)
        if record is None or record.appointment_id != appointment_id:
            return None

        return record

    async def get_document_by_id(self, record_id: int) -> MedicalRecord | None:
        """Return the current document for a handler that will authorize its appointment."""
        return await self.medical_record_repository.get_by_id(record_id)

    async def delete_document(self, record_id: int, appointment_id: int) -> bool:
        """Delete an appointment-scoped document and then its database row.

        Files are removed by the bot process itself.  The recorded path must
        resolve under OUTPUT_DIR, so an altered database value cannot make the
        bot delete an arbitrary VM file.
        """
        async with self._document_lock(record_id):
            record = await self.get_document_for_appointment(record_id, appointment_id)
            if record is None or record.id is None:
                return False

            document_path = self._validated_document_path(record.file_path) if record.file_path else None
            generation_is_active = (
                record.id in self._generating_record_ids
                or record.status is MedicalRecordStatus.GENERATING
            )
            if generation_is_active:
                self._cancelled_generation_ids.add(record.id)

            try:
                if document_path is not None and document_path.exists():
                    document_path.unlink()
                return await self.medical_record_repository.delete_by_id(record.id)
            except OSError as exc:
                if generation_is_active:
                    self._cancelled_generation_ids.discard(record.id)
                raise MedicalRecordDeletionError("Не удалось удалить файл документа.") from exc

    async def mark_for_regeneration(self, record_id: int) -> None:
        """Reset a specific record back to pending so it can be regenerated.

        Used when the stored file_path no longer points at a document on
        disk (e.g. it was deleted manually). Takes the record id directly
        since callers always already hold the record they want regenerated.
        """
        await self.medical_record_repository.mark_pending(record_id, get_current_tashkent_time())

    async def ensure_file_exists(self, record: MedicalRecord) -> MedicalRecord | None:
        """Return `record` unchanged if its file is present on disk, regenerating it in place otherwise.

        Regeneration is keyed by the record's own diagnosis, not the
        appointment's current purpose, so a since-changed purpose can never
        redirect the regeneration onto a different record.

        Returns None if regeneration fails to produce a usable file.
        """
        if record.id is None:
            return None

        current_record = await self.get_document_for_appointment(record.id, record.appointment_id)
        if current_record is None or current_record.status not in READY_STATUSES:
            return None

        if current_record.file_path and Path(current_record.file_path).exists():
            return current_record

        logger.warning(
            "Medical record file missing on disk for appointment %s: %s",
            current_record.appointment_id, current_record.file_path,
        )
        await self.mark_for_regeneration(current_record.id)
        regenerated = await self.generate(
            current_record.appointment_id,
            current_record.diagnosis,
            expected_record_id=current_record.id,
        )

        if (
            regenerated is None
            or regenerated.status not in READY_STATUSES
            or not regenerated.file_path
            or not Path(regenerated.file_path).exists()
        ):
            return None

        return regenerated

    @staticmethod
    def _paginate_math(total_count: int, page: int) -> tuple[int, int]:
        total_pages = ceil(total_count / MEDICAL_RECORDS_PER_PAGE) if total_count > 0 else 1
        return max(1, min(page, total_pages)), total_pages

    @staticmethod
    def _validated_document_path(file_path: str) -> Path:
        """Return a deletable document path after enforcing OUTPUT_DIR scope."""
        try:
            output_root = OUTPUT_DIR.resolve(strict=False)
            document_path = Path(file_path)
            if not document_path.is_absolute() or ".." in document_path.parts:
                raise MedicalRecordDeletionError("Недопустимый путь к файлу документа.")

            document_path.relative_to(output_root)
            if document_path.is_symlink() or document_path.is_dir():
                raise MedicalRecordDeletionError("Недопустимый путь к файлу документа.")

            resolved_document_path = document_path.resolve(strict=False)
            resolved_document_path.relative_to(output_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MedicalRecordDeletionError("Недопустимый путь к файлу документа.") from exc

        return resolved_document_path

    async def _generation_was_deleted(self, record_id: int) -> bool:
        if record_id in self._cancelled_generation_ids:
            return True
        return await self.medical_record_repository.get_by_id(record_id) is None

    def _document_lock(self, record_id: int) -> asyncio.Lock:
        return self._document_locks.setdefault(record_id, asyncio.Lock())

    async def _mark_failed_if_current(self, record_id: int, error_message: str) -> None:
        if await self._generation_was_deleted(record_id):
            return
        await self.medical_record_repository.mark_failed(
            record_id, error_message, get_current_tashkent_time(),
        )

    @staticmethod
    def _remove_rendered_file(file_path: str) -> None:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove document rendered after its record was deleted: %s", file_path)

    @staticmethod
    def _is_stale_generating(record: MedicalRecord) -> bool:
        if record.updated_at is None:
            return True

        try:
            updated_at = datetime.fromisoformat(record.updated_at)
        except ValueError:
            return True

        return get_current_tashkent_datetime() - updated_at > timedelta(minutes=STALE_GENERATING_MINUTES)

    def _build_output_path(self, appointment: Appointment, client: User, diagnosis: str, record_id: int) -> Path:
        clinic_segment = _sanitize_path_segment(appointment.clinic_name or "Клиника", max_length=PATH_SEGMENT_MAX_LENGTH)
        doctor_segment = _sanitize_path_segment(
            appointment.doctor_full_name or "Без_врача", max_length=PATH_SEGMENT_MAX_LENGTH,
        )
        patient_segment = _sanitize_path_segment(client.full_name or "Пациент", max_length=PATH_SEGMENT_MAX_LENGTH)
        diagnosis_segment = _sanitize_path_segment(
            diagnosis or "Без_диагноза", max_length=DIAGNOSIS_SEGMENT_MAX_LENGTH,
        )
        date_segment = _sanitize_path_segment(format_appointment_card_datetime(appointment.datetime))

        filename = f"{date_segment}_{diagnosis_segment}_{record_id}.docx"

        return OUTPUT_DIR / clinic_segment / doctor_segment / patient_segment / filename

    async def _generate_ai_fields(self, purpose: str, client: User) -> tuple[dict, bool]:
        prompt = self._build_prompt(purpose, client)

        llm_response = await self.chat_llm.generate(prompt)

        return {
            "complaints": llm_response["complaints"],
            "examination": llm_response["examination"],
            "diseases": llm_response["diseases"],
            "treatment": llm_response["treatment"],
            "tooth_map": llm_response["tooth_map"],
        }, False

    def _build_prompt(self, purpose: str, client: User) -> str:
        patient_summary = (
            f"ФИО: {client.full_name}, "
            f"пол: {GENDER_LABELS.get(client.gender, 'не указан')}, "
            f"дата рождения: {self._format_birth_date(client.birth_date) or 'не указана'}"
        )

        return prompt_builder.build_user_prompt(patient_summary, purpose)

    @staticmethod
    def _format_birth_date(birth_date: str | None) -> str:
        if birth_date is None:
            return ""
        return format_appointment_card_datetime(birth_date).split(" ")[0]
