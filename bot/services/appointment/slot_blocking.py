from datetime import timedelta

from bot.config.booking_config import SLOT_STEP_MINUTES
from bot.exceptions.appointment_exceptions import InvalidPurposeError
from bot.exceptions.blocked_slot_exceptions import (
    BlockedSlotAlreadyCancelledError,
    BlockedSlotNotFoundError,
    InvalidBlockRangeError,
    InvalidBlockReasonError,
)
from bot.exceptions.user_exceptions import UserNotFoundError
from bot.models.appointment import Appointment
from bot.models.blocked_slot import BlockedSlot
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.blocked_slot_repository import BlockedSlotRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import (
    datetime_ranges_overlap,
    format_datetime_for_db,
    get_current_tashkent_time,
    get_current_tashkent_datetime,
    parse_db_datetime,
    parse_ru_datetime,
)
from bot.utils.appointment_enums import AppointmentStatus
from bot.validators.validators import validate_purpose

_INVALID_RANGE_FORMAT_MESSAGE = {
    "ru": "Не удалось распознать дату и время. Проверьте формат и попробуйте снова.",
    "uz": "Sana va vaqtni aniqlab bo'lmadi. Formatni tekshirib, qayta urinib ko'ring.",
}

_INVALID_RANGE_ORDER_MESSAGE = {
    "ru": "Окончание блокировки должно быть позже её начала.",
    "uz": "Bloklash tugashi uning boshlanishidan keyin bo'lishi kerak.",
}

_INVALID_RANGE_FULLY_PAST_MESSAGE = {
    "ru": "Нельзя заблокировать полностью прошедший интервал.",
    "uz": "To'liq o'tib ketgan oraliqni bloklab bo'lmaydi.",
}

_INVALID_RANGE_START_TOO_OLD_MESSAGE = {
    "ru": "Начало блокировки не может быть более чем на 7 дней в прошлом. Проверьте год и дату.",
    "uz": "Bloklash boshlanishi 7 kundan ortiq o'tmishda bo'lishi mumkin emas. Yil va sanani tekshiring.",
}

_INVALID_RANGE_START_TOO_FAR_MESSAGE = {
    "ru": "Начало блокировки не может быть более чем на 90 дней вперёд. Проверьте год и дату.",
    "uz": "Bloklash boshlanishi 90 kundan ortiq oldinga bo'lishi mumkin emas. Yil va sanani tekshiring.",
}

_INVALID_REASON_MESSAGE = {
    "ru": "Опишите причину блокировки (от 2 до 100 символов). Например: Отпуск, Больничный.",
    "uz": "Bloklash sababini yozing (2 dan 100 belgigacha). Masalan: Ta'til, Kasallik.",
}

_BLOCK_NOT_FOUND_MESSAGE = {
    "ru": "Блокировка не найдена.",
    "uz": "Bloklash topilmadi.",
}

_BLOCK_ALREADY_CANCELLED_MESSAGE = {
    "ru": "Эта блокировка уже отменена.",
    "uz": "Bu bloklash allaqachon bekor qilingan.",
}

_ADMIN_NOT_FOUND_MESSAGE = {
    "ru": "Сотрудник не найден.",
    "uz": "Xodim topilmadi.",
}

_MAX_BLOCK_START_AGE = timedelta(days=7)
_MAX_BLOCK_START_FUTURE = timedelta(days=90)


class SlotBlockingService:
    def __init__(
        self,
        blocked_slot_repository: BlockedSlotRepository,
        appointment_repository: AppointmentRepository,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
        clinic_repository: ClinicRepository,
    ):
        self.blocked_slot_repository = blocked_slot_repository
        self.appointment_repository = appointment_repository
        self.user_repository = user_repository
        self.staff_repository = staff_repository
        self.clinic_repository = clinic_repository

    async def validate_range(self, start_raw: str, end_raw: str) -> tuple[str, str]:
        start_parsed = parse_ru_datetime(start_raw)
        end_parsed = parse_ru_datetime(end_raw)
        if start_parsed is None or end_parsed is None:
            raise InvalidBlockRangeError(_INVALID_RANGE_FORMAT_MESSAGE)

        start = format_datetime_for_db(start_parsed)
        end = format_datetime_for_db(end_parsed)
        now_dt = get_current_tashkent_datetime()
        now = format_datetime_for_db(now_dt)

        earliest_allowed_start = format_datetime_for_db(now_dt - _MAX_BLOCK_START_AGE)
        if start < earliest_allowed_start:
            raise InvalidBlockRangeError(_INVALID_RANGE_START_TOO_OLD_MESSAGE)

        latest_allowed_start = format_datetime_for_db(now_dt + _MAX_BLOCK_START_FUTURE)
        if start > latest_allowed_start:
            raise InvalidBlockRangeError(_INVALID_RANGE_START_TOO_FAR_MESSAGE)

        if end <= start:
            raise InvalidBlockRangeError(_INVALID_RANGE_ORDER_MESSAGE)

        if end <= now:
            raise InvalidBlockRangeError(_INVALID_RANGE_FULLY_PAST_MESSAGE)

        return start, end

    def validate_reason(self, raw: str) -> str:
        try:
            return validate_purpose(raw)
        except InvalidPurposeError:
            raise InvalidBlockReasonError(_INVALID_REASON_MESSAGE)

    async def find_conflicts(
        self, clinic_id: int, staff_id: int | None, start: str, end: str
    ) -> list[Appointment]:
        """Appointments whose occupied interval [datetime, +SLOT_STEP_MINUTES)
        overlaps the block range [start, end)."""
        start_parsed = parse_db_datetime(start)
        end_parsed = parse_db_datetime(end)
        if start_parsed is None or end_parsed is None:
            raise InvalidBlockRangeError(_INVALID_RANGE_FORMAT_MESSAGE)

        slot_step = timedelta(minutes=SLOT_STEP_MINUTES)
        candidate_start = format_datetime_for_db(start_parsed - slot_step)

        candidates = await self.appointment_repository.get_appointments_in_range(
            clinic_id, staff_id, candidate_start, end
        )

        conflicts: list[Appointment] = []
        for appointment in candidates:
            appointment_start = parse_db_datetime(appointment.datetime)
            # Unlike _is_slot_blocked, an unparseable datetime is excluded here:
            # conflicts get cancelled, so over-inclusion would kill a real booking.
            if appointment_start is None:
                continue
            if datetime_ranges_overlap(
                appointment_start, appointment_start + slot_step, start_parsed, end_parsed
            ):
                conflicts.append(appointment)

        return conflicts

    async def find_proposed_datetime_conflicts(
        self, clinic_id: int, staff_id: int | None, start: str, end: str
    ) -> list[Appointment]:
        """Appointments whose pending reschedule proposal [proposed_datetime,
        +SLOT_STEP_MINUTES) overlaps the block range [start, end). Never
        cancelled here -- the appointment's current time may still be free."""
        start_parsed = parse_db_datetime(start)
        end_parsed = parse_db_datetime(end)
        if start_parsed is None or end_parsed is None:
            raise InvalidBlockRangeError(_INVALID_RANGE_FORMAT_MESSAGE)

        slot_step = timedelta(minutes=SLOT_STEP_MINUTES)
        candidate_start = format_datetime_for_db(start_parsed - slot_step)

        candidates = await self.appointment_repository.get_appointments_with_proposed_datetime_in_range(
            clinic_id, staff_id, candidate_start, end
        )

        conflicts: list[Appointment] = []
        for appointment in candidates:
            proposed_start = parse_db_datetime(appointment.proposed_datetime)
            if proposed_start is None:
                continue
            if appointment.status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
                continue
            if datetime_ranges_overlap(
                proposed_start, proposed_start + slot_step, start_parsed, end_parsed
            ):
                conflicts.append(appointment)

        return conflicts

    async def find_cancelable_conflicts(
        self, clinic_id: int, staff_id: int | None, start: str, end: str
    ) -> list[Appointment]:
        conflicts = await self.find_conflicts(clinic_id, staff_id, start, end)
        return self._filter_cancelable(conflicts)

    @staticmethod
    def _filter_cancelable(conflicts: list[Appointment]) -> list[Appointment]:
        return [
            appointment for appointment in conflicts
            if appointment.status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        ]

    async def create_block(
        self,
        admin_telegram_id: int,
        clinic_id: int,
        staff_id: int | None,
        start_raw: str,
        end_raw: str,
        reason: str,
    ) -> tuple[BlockedSlot, list[Appointment]]:
        reason = self.validate_reason(reason)
        start, end = await self.validate_range(start_raw, end_raw)
        conflicts = await self.find_conflicts(clinic_id, staff_id, start, end)

        acting_user = await self.user_repository.get_user_by_telegram_id(admin_telegram_id)
        if acting_user is None:
            raise UserNotFoundError(_ADMIN_NOT_FOUND_MESSAGE)
        acting_user_id = acting_user.ID
        status_updated_at = get_current_tashkent_time()

        cancelled_appointments = self._filter_cancelable(conflicts)

        block = BlockedSlot(
            clinic_id=clinic_id,
            staff_id=staff_id,
            start_datetime=start,
            end_datetime=end,
            reason=reason,
            created_by=acting_user_id,
            created_at=get_current_tashkent_time(),
        )
        created_block = await self.blocked_slot_repository.create_block(block)

        for appointment in cancelled_appointments:
            await self.appointment_repository.update_appointment_status(
                appointment.id, AppointmentStatus.CANCELLED, status_updated_at
            )
            appointment.status = AppointmentStatus.CANCELLED
            appointment.status_updated_at = status_updated_at

        return created_block, cancelled_appointments

    async def list_active_blocks(self, clinic_id: int) -> list[BlockedSlot]:
        blocks = await self.blocked_slot_repository.get_active_blocks_by_clinic(clinic_id)
        now = format_datetime_for_db(get_current_tashkent_datetime())

        return [block for block in blocks if block.end_datetime > now]

    async def cancel_block(self, admin_telegram_id: int, block_id: int) -> BlockedSlot:
        block = await self.blocked_slot_repository.get_block_by_id(block_id)
        if block is None:
            raise BlockedSlotNotFoundError(_BLOCK_NOT_FOUND_MESSAGE)

        await self._ensure_can_manage_block(admin_telegram_id, block)

        if block.cancelled_at is not None:
            raise BlockedSlotAlreadyCancelledError(_BLOCK_ALREADY_CANCELLED_MESSAGE)

        cancelled_at = get_current_tashkent_time()
        cancelled = await self.blocked_slot_repository.cancel_block(block_id, cancelled_at)
        if not cancelled:
            raise BlockedSlotAlreadyCancelledError(_BLOCK_ALREADY_CANCELLED_MESSAGE)

        return await self.blocked_slot_repository.get_block_by_id(block_id)

    async def _ensure_can_manage_block(self, admin_telegram_id: int, block: BlockedSlot) -> None:
        staff_record = await self.staff_repository.get_staff(admin_telegram_id)
        clinic = await resolve_staff_clinic(self.staff_repository, self.clinic_repository, admin_telegram_id)

        if block.clinic_id != clinic.clinic_id:
            raise BlockedSlotNotFoundError(_BLOCK_NOT_FOUND_MESSAGE)

        if staff_record.visibility_scope not in (None, "own"):
            return

        acting_user = await self.user_repository.get_user_by_telegram_id(admin_telegram_id)
        if acting_user is None:
            raise UserNotFoundError(_ADMIN_NOT_FOUND_MESSAGE)

        # Own-scope doctors may only manage blocks tied to their own staff_id.
        # A clinic-wide block (staff_id is None) is not "theirs" either -- it
        # was created/managed by a clinic-scope admin, same as list_active_blocks
        # scoping in the handler's render_blocks_list.
        if block.staff_id != acting_user.ID:
            raise BlockedSlotNotFoundError(_BLOCK_NOT_FOUND_MESSAGE)
