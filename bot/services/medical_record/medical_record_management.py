import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from bot.config.clinic_instances import MEDICAL_RECORD_TEMPLATE_BY_INSTANCE
from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
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

logger = logging.getLogger(__name__)

GENDER_LABELS = {"male": "Мужской", "female": "Женский"}

READY_STATUSES = (MedicalRecordStatus.READY, MedicalRecordStatus.READY_PARTIAL)

ALREADY_GENERATED_STATUSES = (*READY_STATUSES, MedicalRecordStatus.GENERATING)

EMPTY_AI_FIELDS = {
    "complaints": "",
    "diseases": "",
    "examination": "",
    "treatment": "",
    "tooth_map": [],
}

DIAGNOSIS_SEGMENT_MAX_LENGTH = 30
PATH_SEGMENT_MAX_LENGTH = 30
STALE_GENERATING_MINUTES = 5

_UNSAFE_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*]')

_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


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

    async def generate(self, appointment_id: int, diagnosis: str | None = None) -> MedicalRecord | None:
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

        On LLM failure (after ChatLLM's own retries are exhausted), the
        document is still generated with empty strings for the four
        AI-authored fields, tooth_map defaulting to an empty list, and the
        record is marked ready_partial, so the "get document" button never
        blocks on the LLM being unavailable.
        """
        appointment = await self.appointment_management.get_appointment_by_id(appointment_id)
        if appointment is None:
            logger.warning("Medical record generation: appointment %s not found", appointment_id)
            return None

        if diagnosis is None:
            diagnosis = appointment.purpose
        diagnosis = diagnosis or ""

        existing = await self.medical_record_repository.get_by_appointment_and_diagnosis(appointment_id, diagnosis)
        if existing is not None and existing.status in ALREADY_GENERATED_STATUSES:
            stale_generating = (
                existing.status is MedicalRecordStatus.GENERATING and self._is_stale_generating(existing)
            )
            if not stale_generating:
                return existing

        record = existing or await self.medical_record_repository.create_pending(
            appointment_id, diagnosis, get_current_tashkent_time(),
        )
        await self.medical_record_repository.mark_generating(record.id, get_current_tashkent_time())

        client = await self.appointment_management.get_client_by_id(appointment.client_id)
        if client is None:
            await self.medical_record_repository.mark_failed(
                record.id, "Клиент не найден.", get_current_tashkent_time(),
            )
            return None

        template_path = MEDICAL_RECORD_TEMPLATE_BY_INSTANCE.get(self.instance)
        if template_path is None:
            logger.info(
                "Шаблон истории болезни не настроен для инстанса %s, генерация пропущена (appointment %s).",
                self.instance, appointment_id,
            )
            await self.medical_record_repository.mark_failed(
                record.id, "Шаблон истории болезни не настроен для этой клиники.", get_current_tashkent_time(),
            )
            return None

        ai_fields, partial = await self._generate_ai_fields(diagnosis, client)
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
            logger.exception("Failed to render medical record docx for appointment %s: %s", appointment_id, exc)
            await self.medical_record_repository.mark_failed(record.id, str(exc), get_current_tashkent_time())
            return None

        await self.medical_record_repository.mark_ready(
            record.id, file_path, partial=partial, updated_at=get_current_tashkent_time(),
        )

        return await self.medical_record_repository.get_by_appointment_and_diagnosis(appointment_id, diagnosis)

    async def get_ready_documents(self, appointment_id: int) -> list[MedicalRecord]:
        """Return every already-generated, ready document for an appointment."""
        return await self.medical_record_repository.list_ready_by_appointment_id(appointment_id)

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
        if record.file_path and Path(record.file_path).exists():
            return record

        logger.warning(
            "Medical record file missing on disk for appointment %s: %s",
            record.appointment_id, record.file_path,
        )
        await self.mark_for_regeneration(record.id)
        regenerated = await self.generate(record.appointment_id, record.diagnosis)

        if (
            regenerated is None
            or regenerated.status not in READY_STATUSES
            or not regenerated.file_path
            or not Path(regenerated.file_path).exists()
        ):
            return None

        return regenerated

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

        try:
            llm_response = await self.chat_llm.generate(prompt)
        except MedicalRecordGenerationError as exc:
            logger.warning("LLM generation failed, falling back to empty AI fields: %s", exc)
            return dict(EMPTY_AI_FIELDS), True

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
