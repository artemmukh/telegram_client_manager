import logging

from bot.config.clinic_instances import MEDICAL_RECORD_TEMPLATE_BY_INSTANCE
from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.repositories.medical_record_repository import MedicalRecordRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.document_generator.pydocx import create_docx
from bot.services.llm.agent import ChatLLM
from bot.services.utils.date_parser import format_appointment_card_datetime
from bot.utils.medical_record_enums import MedicalRecordStatus

logger = logging.getLogger(__name__)

GENDER_LABELS = {"male": "Мужской", "female": "Женский"}

LLM_PROMPT_TEMPLATE = """Ты врач стоматолог.
На основе диагноза и шаблона заполни поля.
Верни ТОЛЬКО JSON.
Никаких пояснений.
Структура:
{{
    "complaints": "",
    "anamnesis": "",
    "objective": "",
    "diagnosis_reason": "",
    "treatment_plan": ""
}}
Пациент:
{patient}
Диагноз:
{diagnosis}
Шаблон:
{template}

Верни строго JSON.
Запрещено:
- Markdown
- ```json
- комментарии
- пояснения
Все ключи должны присутствовать.
Если информации недостаточно —
оставь пустую строку."""

TEMPLATE_FIELDS_DESCRIPTION = (
    "Жалобы, Перенесённые и сопутствующие заболевания, Объективный осмотр, Диагноз, Лечение"
)

ALREADY_GENERATED_STATUSES = (
    MedicalRecordStatus.READY,
    MedicalRecordStatus.READY_PARTIAL,
    MedicalRecordStatus.GENERATING,
)

EMPTY_AI_FIELDS = {
    "complaints": "",
    "diseases": "",
    "examination": "",
    "diagnosis": "",
    "treatment": "",
}


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

    async def generate(self, appointment_id: int) -> MedicalRecord | None:
        """Generate the medical record docx for a completed appointment.

        Idempotent: if a record already exists with status ready, ready_partial,
        or generating, the existing record is returned unchanged and no new
        generation is started. If the appointment or its client cannot be
        found, the record (if any) is marked failed and None is returned.

        On LLM failure (after ChatLLM's own retries are exhausted), the
        document is still generated with empty strings for the five
        AI-authored fields and the record is marked ready_partial, so the
        "get document" button never blocks on Ollama being unavailable.
        """
        existing = await self.medical_record_repository.get_by_appointment_id(appointment_id)
        if existing is not None and existing.status in ALREADY_GENERATED_STATUSES:
            return existing

        record = existing or await self.medical_record_repository.create_pending(appointment_id)
        await self.medical_record_repository.mark_generating(record.id)

        appointment = await self.appointment_management.get_appointment_by_id(appointment_id)
        if appointment is None:
            await self.medical_record_repository.mark_failed(record.id, "Запись не найдена.")
            return None

        client = await self.appointment_management.get_client_by_id(appointment.client_id)
        if client is None:
            await self.medical_record_repository.mark_failed(record.id, "Клиент не найден.")
            return None

        template_path = MEDICAL_RECORD_TEMPLATE_BY_INSTANCE.get(self.instance)
        if template_path is None:
            logger.info(
                "Шаблон истории болезни не настроен для инстанса %s, генерация пропущена (appointment %s).",
                self.instance, appointment_id,
            )
            await self.medical_record_repository.mark_failed(
                record.id, "Шаблон истории болезни не настроен для этой клиники.",
            )
            return None

        ai_fields, partial = await self._generate_ai_fields(appointment.purpose, client)

        data = {
            "appointment_date": format_appointment_card_datetime(appointment.datetime),
            "full_name": client.full_name,
            "gender": GENDER_LABELS.get(client.gender, ""),
            "birth_date": self._format_birth_date(client.birth_date),
            "phone": client.phone,
            **ai_fields,
        }

        try:
            file_path = await create_docx(data, appointment.purpose, appointment_id, template_path)
        except Exception as exc:
            logger.exception("Failed to render medical record docx for appointment %s: %s", appointment_id, exc)
            await self.medical_record_repository.mark_failed(record.id, str(exc))
            return None

        await self.medical_record_repository.mark_ready(record.id, file_path, partial=partial)

        return await self.medical_record_repository.get_by_appointment_id(appointment_id)

    async def get_or_generate(self, appointment_id: int) -> tuple[MedicalRecord, bool]:
        """Return the medical record for an appointment, creating it if needed.

        Returns a (record, needs_generation) tuple with three possible
        outcomes the caller must handle:

        - record.status in (ready, ready_partial), needs_generation=False:
          generation already finished, send record.file_path to the user.
        - record.status in (pending, generating), needs_generation=False:
          generation is already in flight (dispatched earlier by the
          completion job/handler), tell the user to check back shortly.
        - record.status == pending, needs_generation=True:
          no record existed before this call (edge case - the appointment
          reached COMPLETED without generation ever being triggered); a
          pending row was just created here as a fallback. The caller MUST
          call AppointmentScheduler.schedule_medical_record_generation
          (or await generate_medical_record_job directly) to actually start
          generation, then tell the user to check back shortly.
        """
        record = await self.medical_record_repository.get_by_appointment_id(appointment_id)
        if record is not None:
            return record, False

        record = await self.medical_record_repository.create_pending(appointment_id)
        return record, True

    async def _generate_ai_fields(self, purpose: str, client: User) -> tuple[dict, bool]:
        prompt = self._build_prompt(purpose, client)

        try:
            llm_response = await self.chat_llm.generate(prompt)
        except MedicalRecordGenerationError as exc:
            logger.warning("LLM generation failed, falling back to empty AI fields: %s", exc)
            return dict(EMPTY_AI_FIELDS), True

        return {
            "complaints": llm_response["complaints"],
            "diseases": llm_response["anamnesis"],
            "examination": llm_response["objective"],
            "diagnosis": llm_response["diagnosis_reason"],
            "treatment": llm_response["treatment_plan"],
        }, False

    def _build_prompt(self, purpose: str, client: User) -> str:
        patient_summary = (
            f"ФИО: {client.full_name}, "
            f"пол: {GENDER_LABELS.get(client.gender, 'не указан')}, "
            f"дата рождения: {self._format_birth_date(client.birth_date) or 'не указана'}"
        )

        return LLM_PROMPT_TEMPLATE.format(
            patient=patient_summary,
            diagnosis=purpose,
            template=TEMPLATE_FIELDS_DESCRIPTION,
        )

    @staticmethod
    def _format_birth_date(birth_date: str | None) -> str:
        if birth_date is None:
            return ""
        return format_appointment_card_datetime(birth_date).split(" ")[0]
