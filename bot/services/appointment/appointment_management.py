from collections import Counter
from datetime import date, datetime, timedelta

from bot.config.booking_config import (
    CANCELLATION_COOLDOWN_WINDOW_MINUTES,
    MAX_BOOKINGS_PER_SLOT,
    MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW,
    MAX_PENDING_REQUESTS_PER_CLIENT,
)
from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyDecidedError,
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    AwaitingClinicDecisionError,
    BookingTooSoonError,
    CancellationCooldownExceededError,
    CancellationWindowExpiredError,
    NegotiationInProgressError,
    NoPendingProposalError,
    PendingRequestLimitExceededError,
    SlotUnavailableError,
)
from bot.exceptions.user_exceptions import UserNotFoundError, PhoneAlreadyExistsError
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import get_current_tashkent_time, get_current_tashkent_datetime
from bot.services.utils.booking_day_helpers import (
    find_first_available_week_offset as _find_first_available_week_offset,
    generate_working_days,
)
from bot.services.utils.slot_helpers import generate_available_slots
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_datetime, validate_price, validate_purpose, validate_full_name, \
    validate_phone, SEARCH_NAME_PATTERN

CANCELLATION_CUTOFF_HOURS = 1
MIN_LEAD_TIME = timedelta(hours=2, minutes=30)
SLOT_UNAVAILABLE_MESSAGE = {
    "ru": "Это время уже занято другой записью, выберите другое.",
    "uz": "Bu vaqt boshqa yozuv tomonidan band qilingan, boshqasini tanlang.",
}
DUPLICATE_CLIENT_SLOT_MESSAGE = {
    "ru": "У этого клиента уже есть запись на это время.",
    "uz": "Bu mijozning bu vaqtga allaqachon yozuvi bor.",
}

_DOCTOR_NOT_FOUND_MESSAGE = {
    "ru": "Врач не найден.",
    "uz": "Shifokor topilmadi.",
}

_CLIENT_NOT_LINKED_MESSAGE = {
    "ru": "Клиент не найден или не привязан к клинике.",
    "uz": "Mijoz topilmadi yoki klinikaga bog'lanmagan.",
}

_CLIENT_NOT_FOUND_MESSAGE = {
    "ru": "Клиент не найден.",
    "uz": "Mijoz topilmadi.",
}

_STAFF_MEMBER_NOT_FOUND_MESSAGE = {
    "ru": "Специалист не найден.",
    "uz": "Mutaxassis topilmadi.",
}

_PENDING_REQUEST_LIMIT_MESSAGE = {
    "ru": "У вас уже есть заявка на рассмотрении. Дождитесь решения клиники, прежде чем создавать новую.",
    "uz": "Sizda allaqachon ko'rib chiqilayotgan ariza bor. Yangisini yaratishdan oldin klinika javobini kuting.",
}

_CANCELLATION_COOLDOWN_MESSAGE = {
    "ru": "Вы слишком часто отменяете заявки. Подождите немного, прежде чем создать новую.",
    "uz": "Siz arizalarni juda tez-tez bekor qilyapsiz. Yangisini yaratishdan oldin biroz kuting.",
}

_AWAIT_CLINIC_DECISION_MESSAGE = {
    "ru": "Дождитесь решения клиники по вашей заявке.",
    "uz": "Arizangiz bo'yicha klinika javobini kuting.",
}

_CONFIRM_NOT_AVAILABLE_MESSAGE = {
    "ru": (
        "Эта запись больше недоступна для подтверждения. "
        "Возможно, она была отменена или уже завершена. Обновите список записей."
    ),
    "uz": (
        "Bu yozuv endi tasdiqlash uchun mavjud emas. "
        "Ehtimol, u bekor qilingan yoki allaqachon yakunlangan. Yozuvlar ro'yxatini yangilang."
    ),
}

_CANCEL_NOT_AVAILABLE_MESSAGE = {
    "ru": (
        "Эта запись больше недоступна для отмены. "
        "Возможно, она уже была отменена или завершена. Обновите список записей."
    ),
    "uz": (
        "Bu yozuv endi bekor qilish uchun mavjud emas. "
        "Ehtimol, u allaqachon bekor qilingan yoki yakunlangan. Yozuvlar ro'yxatini yangilang."
    ),
}

_REQUEST_NO_LONGER_AVAILABLE_MESSAGE = {
    "ru": "Эта заявка больше недоступна.",
    "uz": "Bu ariza endi mavjud emas.",
}

_RECORD_NO_LONGER_AVAILABLE_MESSAGE = {
    "ru": "Эта запись больше недоступна.",
    "uz": "Bu yozuv endi mavjud emas.",
}

_CANCELLATION_WINDOW_EXPIRED_MESSAGE = {
    "ru": "Отмена возможна не позднее чем за 1 час, свяжитесь с клиникой",
    "uz": "Bekor qilish faqat 1 soat oldin mumkin, klinika bilan bog'laning",
}

_PROPOSAL_PENDING_CLIENT_ANSWER_MESSAGE = {
    "ru": "По этой заявке уже предложено новое время. Дождитесь ответа клиента.",
    "uz": "Bu ariza uchun allaqachon yangi vaqt taklif qilingan. Mijoz javobini kuting.",
}

_PROPOSAL_ALREADY_PENDING_MESSAGE = {
    "ru": "По этой записи уже есть предложение, ожидающее ответа.",
    "uz": "Bu yozuv uchun allaqachon javob kutilayotgan taklif bor.",
}

_RESCHEDULE_NOT_AVAILABLE_MESSAGE = {
    "ru": (
        "Перенос доступен только для подтверждённых записей, ещё не решённых "
        "клиникой записей или собственных заявок на самозапись, ожидающих решения клиники."
    ),
    "uz": (
        "Ko'chirish faqat tasdiqlangan yozuvlar, klinika hali qaror qabul qilmagan yozuvlar "
        "yoki klinika javobini kutayotgan o'z mustaqil yozilish arizalari uchun mavjud."
    ),
}

_NO_PENDING_PROPOSAL_MESSAGE = {
    "ru": "По этой записи нет предложенного времени, ожидающего ответа.",
    "uz": "Bu yozuv uchun javob kutilayotgan taklif qilingan vaqt yo'q.",
}

_NO_CLIENT_PROPOSAL_MESSAGE = {
    "ru": "Нет предложения от клиента, ожидающего решения.",
    "uz": "Mijozdan qaror kutilayotgan taklif yo'q.",
}

_CLIENT_NOT_FOUND_BY_PHONE_MESSAGE = {
    "ru": "Клиент с таким номером не найден. Сначала создайте клиента.",
    "uz": "Bu raqamli mijoz topilmadi. Avval mijozni yarating.",
}

_STAFF_NOT_FOUND_MESSAGE = {
    "ru": "Сотрудник не найден.",
    "uz": "Xodim topilmadi.",
}

_BOOKING_TOO_SOON_MESSAGE = {
    "ru": "Время записи должно быть не менее чем через 2 часа от текущего момента, свяжитесь с клиникой.",
    "uz": "Yozuv vaqti hozirgi vaqtdan kamida 2 soat keyin bo'lishi kerak, klinika bilan bog'laning.",
}

_OTHER_STAFF_LABEL = {
    "ru": "Другой сотрудник",
    "uz": "Boshqa xodim",
}

_DEFAULT_OUTCOME_TEXT = {
    "ru": "решение принято",
    "uz": "qaror qabul qilindi",
}

_BOOKING_ALREADY_DECIDED_MESSAGE = {
    "ru": "Эта заявка уже обработана",
    "uz": "Bu ariza allaqachon ko'rib chiqilgan",
}

_RESCHEDULE_ALREADY_DECIDED_MESSAGE = {
    "ru": "Заявка на перенос уже обработана",
    "uz": "Ko'chirish arizasi allaqachon ko'rib chiqilgan",
}

_COMPLETION_ALREADY_DECIDED_MESSAGE = {
    "ru": "Запись уже обработана",
    "uz": "Yozuv allaqachon ko'rib chiqilgan",
}


class AppointmentManagement:
    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
        clinic_repository: ClinicRepository,
        client_management=None,
        client_clinic_repository: ClientClinicRepository | None = None,
    ):
        self.appointment_repository = appointment_repository
        self.user_repository = user_repository
        self.staff_repository = staff_repository
        self.clinic_repository = clinic_repository
        self.client_management = client_management
        self.client_clinic_repository = client_clinic_repository

    async def create_appointment(self, doctor_telegram_id: int, data: dict) -> Appointment:
        clinic = await self.get_admin_clinic(doctor_telegram_id)

        client = await self._resolve_client(data["phone"])

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        purpose = validate_purpose(data["purpose"])

        admin = await self.user_repository.get_user_by_telegram_id(doctor_telegram_id)
        if admin is None:
            raise UserNotFoundError(_DOCTOR_NOT_FOUND_MESSAGE)

        doctor_id = admin.ID
        if data.get("staff_user_id") is not None:
            doctor = await self.user_repository.get_user_by_id(data["staff_user_id"])
            if doctor is None:
                raise UserNotFoundError(_DOCTOR_NOT_FOUND_MESSAGE)
            if doctor.clinic_id != clinic.clinic_id:
                raise UserNotFoundError(_DOCTOR_NOT_FOUND_MESSAGE)
            if doctor.ID != admin.ID:
                staff_record = await self.staff_repository.get_staff(doctor_telegram_id)
                if staff_record is None or staff_record.visibility_scope != "clinic":
                    raise UserNotFoundError(_DOCTOR_NOT_FOUND_MESSAGE)
            doctor_id = doctor.ID

        await self._ensure_slot_available(doctor_id, appointment_datetime, None, client.ID)

        if self.client_clinic_repository is not None:
            await self.client_clinic_repository.link_client_to_clinic(client.ID, clinic.clinic_id)

        appointment_dt = datetime.fromisoformat(appointment_datetime)
        now = get_current_tashkent_datetime()
        is_walk_in = appointment_dt - now < MIN_LEAD_TIME

        if client.telegram_user_id is None:
            status = AppointmentStatus.CONFIRMED
        else:
            status = AppointmentStatus.CONFIRMED if is_walk_in else AppointmentStatus.PENDING

        appointment = Appointment(
            clinic_id=clinic.clinic_id,
            client_id=client.ID,
            doctor_id=doctor_id,
            datetime=appointment_datetime,
            purpose=purpose,
            created_by=CreatedBy.ADMIN,
            status=status,
            clinic_name=clinic.name,
            created_at=get_current_tashkent_time(),
        )

        return await self.appointment_repository.create_appointment(appointment)

    async def list_clinic_doctors(self, clinic_id: int) -> list[User]:
        candidates = await self.user_repository.get_staff_users_by_clinic_id(clinic_id)
        staff_records = await self.staff_repository.get_staff_by_clinic_id(clinic_id)
        is_doctor_by_telegram_id = {s.telegram_user_id: s.is_doctor for s in staff_records}

        return [u for u in candidates if is_doctor_by_telegram_id.get(u.telegram_user_id, True)]

    async def list_bookable_staff(self, client_telegram_id: int) -> list[User]:
        client = await self.user_repository.get_user_by_telegram_id(client_telegram_id)
        if client is None or client.clinic_id is None:
            raise UserNotFoundError(_CLIENT_NOT_LINKED_MESSAGE)

        return await self.list_clinic_doctors(client.clinic_id)

    async def list_clinic_doctors_for_creation(self, admin_telegram_id: int) -> list[User]:
        clinic = await self.get_admin_clinic(admin_telegram_id)
        staff_record = await self.staff_repository.get_staff(admin_telegram_id)

        if staff_record is None or staff_record.visibility_scope in (None, "own"):
            return []

        return await self.list_clinic_doctors(clinic.clinic_id)

    async def list_clinic_doctors_for_filter(self, admin_telegram_id: int) -> list[User]:
        clinic_id, doctor_id = await self.resolve_admin_appointment_filter(admin_telegram_id)
        if doctor_id is not None:
            return []

        doctors = await self.list_clinic_doctors(clinic_id)
        return doctors if len(doctors) >= 2 else []

    async def resolve_admin_appointment_filter(self, admin_telegram_id: int) -> tuple[int, int | None]:
        clinic = await self.get_admin_clinic(admin_telegram_id)
        admin_user = await self.user_repository.get_user_by_telegram_id(admin_telegram_id)
        staff_record = await self.staff_repository.get_staff(admin_telegram_id)

        if staff_record is None or staff_record.visibility_scope in (None, "own"):
            return clinic.clinic_id, admin_user.ID if admin_user else None

        return clinic.clinic_id, None

    async def create_self_booking(self, client_telegram_id: int, data: dict) -> Appointment:
        client = await self.user_repository.get_user_by_telegram_id(client_telegram_id)
        if client is None:
            raise UserNotFoundError(_CLIENT_NOT_FOUND_MESSAGE)

        await self.ensure_pending_limit_not_exceeded(client_telegram_id)
        await self.ensure_cancellation_cooldown_not_exceeded(client_telegram_id)

        staff = await self.user_repository.get_user_by_id(data["staff_user_id"])
        if staff is None:
            raise UserNotFoundError(_STAFF_MEMBER_NOT_FOUND_MESSAGE)

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        self._validate_min_lead_time(appointment_datetime)
        purpose = validate_purpose(data["complaint"])

        await self._ensure_slot_available(staff.ID, appointment_datetime, None, client.ID)

        appointment = Appointment(
            clinic_id=client.clinic_id,
            client_id=client.ID,
            doctor_id=staff.ID,
            datetime=appointment_datetime,
            purpose=purpose,
            created_by=CreatedBy.CLIENT,
            status=AppointmentStatus.PENDING,
            clinic_name=client.clinic_name,
            created_at=get_current_tashkent_time(),
        )

        return await self.appointment_repository.create_appointment(appointment)

    async def ensure_pending_limit_not_exceeded(self, client_telegram_id: int) -> None:
        pending_count = await self._count_pending_self_bookings(client_telegram_id)
        if pending_count >= MAX_PENDING_REQUESTS_PER_CLIENT:
            raise PendingRequestLimitExceededError(_PENDING_REQUEST_LIMIT_MESSAGE)

    async def ensure_cancellation_cooldown_not_exceeded(self, client_telegram_id: int) -> None:
        recent_cancellations = await self._count_recent_client_cancellations(client_telegram_id)
        if recent_cancellations >= MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW:
            raise CancellationCooldownExceededError(_CANCELLATION_COOLDOWN_MESSAGE)

    async def get_admin_clinic(self, doctor_telegram_id: int) -> Clinic:
        return await resolve_staff_clinic(
            self.staff_repository, self.clinic_repository, doctor_telegram_id
        )

    async def find_client_by_phone(self, phone: str, clinic_id: int | None = None) -> User | None:
        """Find existing client by phone. Returns None if not found.

        When clinic_id is given, the lookup is scoped to that clinic (admin client-browser
        search). When omitted, it falls back to the global lookup used by the appointment
        creation flow, which must match the (intentionally unscoped) check_or_create_client
        precheck it precedes."""
        phone = normalize_phone(phone.strip())
        if clinic_id is None:
            return await self.user_repository.get_client_by_phone(phone)
        return await self.user_repository.get_client_by_phone_in_clinic(phone, clinic_id)

    async def check_or_create_client(
        self,
        admin_telegram_id: int,
        full_name: str,
        phone: str,
    ) -> User:
        """Check if client exists by phone. If not, create new client via ClientManagement."""
        phone = normalize_phone(phone.strip())

        client = await self.user_repository.get_client_by_phone(phone)
        if client is not None:
            if self.client_clinic_repository is not None:
                clinic = await self.get_admin_clinic(admin_telegram_id)
                await self.client_clinic_repository.link_client_to_clinic(client.ID, clinic.clinic_id)
            return client

        if self.client_management:
            new_client = await self.client_management.create_client(
                admin_telegram_id,
                {"full_name": full_name, "phone": phone}
            )
            if self.client_clinic_repository is not None:
                clinic = await self.get_admin_clinic(admin_telegram_id)
                await self.client_clinic_repository.link_client_to_clinic(new_client.ID, clinic.clinic_id)
            return new_client
        else:
            # Fallback: inline creation if ClientManagement not injected
            # This shouldn't happen in production
            full_name = full_name.strip()
            validate_full_name(full_name, SEARCH_NAME_PATTERN)
            validate_phone(phone)

            clinic = await self.get_admin_clinic(admin_telegram_id)

            if await self.user_repository.phone_exists(phone):
                raise PhoneAlreadyExistsError()

            new_client = User(
                full_name=full_name,
                phone=phone,
                role=Role.CLIENT,
                clinic_id=clinic.clinic_id,
                clinic_name=clinic.name,
                created_at=get_current_tashkent_time(),
            )

            await self.user_repository.create_user(new_client)

            if self.client_clinic_repository is not None:
                await self.client_clinic_repository.link_client_to_clinic(new_client.ID, clinic.clinic_id)

            return new_client

    async def get_appointment_by_id(self, appointment_id: int) -> Appointment | None:
        return await self.appointment_repository.get_appointment_by_id(appointment_id)

    async def get_client_by_id(self, user_id: int) -> User | None:
        return await self.user_repository.get_client_by_id(user_id)

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self.user_repository.get_user_by_telegram_id(telegram_id)

    async def get_appointment_for_client(
        self, appointment_id: int, telegram_user_id: int
    ) -> Appointment | None:
        """Return the appointment only if it exists and belongs to the client
        with the given telegram_user_id. Returns None otherwise."""
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None

        client = await self.user_repository.get_user_by_telegram_id(telegram_user_id)
        if client is None or appointment.client_id != client.ID:
            return None

        return appointment

    async def get_appointment_for_admin(
        self, appointment_id: int, admin_telegram_id: int
    ) -> Appointment | None:
        """Return the appointment only if it exists and is within the admin's
        resolved clinic/doctor scope. Returns None otherwise (including when the
        admin_telegram_id has no matching User row)."""
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None

        admin_user = await self.user_repository.get_user_by_telegram_id(admin_telegram_id)
        if admin_user is None:
            return None

        clinic_id, doctor_id = await self.resolve_admin_appointment_filter(admin_telegram_id)

        if appointment.clinic_id != clinic_id:
            return None

        if doctor_id is not None and appointment.doctor_id != doctor_id:
            return None

        return appointment

    async def resolve_decision_label(self, user_id: int | None) -> dict[str, str]:
        if user_id is None:
            return _OTHER_STAFF_LABEL

        user = await self.user_repository.get_user_by_id(user_id)
        if user is None:
            return _OTHER_STAFF_LABEL

        staff_record = await self.staff_repository.get_staff(user.telegram_user_id)
        is_admin = staff_record is not None and staff_record.visibility_scope == "clinic"
        role_ru = "Администратор" if is_admin else "Доктор"
        role_uz = "Administrator" if is_admin else "Shifokor"

        return {
            "ru": f"{role_ru} {user.full_name}",
            "uz": f"{role_uz} {user.full_name}",
        }

    def resolve_decision_outcome_text(self, appointment: Appointment, kind: str) -> dict[str, str]:
        # The PENDING+no-proposal branches below only match a request that has just
        # been decided by propose_new_datetime (confirm_pending_request/reject_pending_request
        # and accept/reject_client_reschedule always land on CONFIRMED/CANCELLED, never
        # PENDING) -- this function is only ever called after a decision has actually
        # been committed (see _raise_already_decided and invalidate_sibling_notifications
        # call sites), so it can't misfire on a plain, never-touched self-booking request.
        if kind == "booking":
            if appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is None:
                return {"ru": "подтверждена", "uz": "tasdiqlandi"}
            if appointment.status == AppointmentStatus.CANCELLED:
                return {"ru": "отклонена", "uz": "rad etildi"}
            if appointment.status == AppointmentStatus.PENDING and appointment.proposed_datetime is None:
                return {
                    "ru": "назначено новое время, ожидает подтверждения клиента",
                    "uz": "yangi vaqt belgilandi, mijoz tasdiqlashini kutmoqda",
                }
            if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
                return {"ru": "предложено другое время", "uz": "boshqa vaqt taklif qilindi"}
        elif kind == "reschedule":
            if appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is None:
                return {"ru": "перенос принят", "uz": "ko'chirish qabul qilindi"}
            if appointment.status == AppointmentStatus.CANCELLED:
                return {"ru": "перенос отклонён", "uz": "ko'chirish rad etildi"}
            if appointment.status == AppointmentStatus.PENDING and appointment.proposed_datetime is None:
                return {
                    "ru": "время изменено, ожидает подтверждения клиента",
                    "uz": "vaqt o'zgartirildi, mijoz tasdiqlashini kutmoqda",
                }
            if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
                return {"ru": "предложено другое время", "uz": "boshqa vaqt taklif qilindi"}
        elif kind == "completion":
            if appointment.status == AppointmentStatus.COMPLETED:
                return {"ru": "приём завершён", "uz": "qabul yakunlandi"}

        return _DEFAULT_OUTCOME_TEXT

    async def confirm_appointment_by_client(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, _CONFIRM_NOT_AVAILABLE_MESSAGE)

        if appointment.created_by == CreatedBy.CLIENT and appointment.status == AppointmentStatus.PENDING:
            raise AwaitingClinicDecisionError(_AWAIT_CLINIC_DECISION_MESSAGE)

        await self._ensure_slot_available(appointment.doctor_id, appointment.datetime, appointment_id, appointment.client_id)

        return await self.update_status(appointment, AppointmentStatus.CONFIRMED)

    async def cancel_appointment_by_client(
        self, appointment_id: int, telegram_user_id: int, enforce_cutoff: bool = True
    ) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, _CANCEL_NOT_AVAILABLE_MESSAGE)

        if enforce_cutoff and self._is_within_cancellation_cutoff(appointment):
            raise CancellationWindowExpiredError(_CANCELLATION_WINDOW_EXPIRED_MESSAGE)

        if appointment.proposed_datetime is not None:
            await self.appointment_repository.update_proposed_datetime(appointment_id, None)
            await self.appointment_repository.update_proposed_by(appointment_id, None)

        return await self.update_status(appointment, AppointmentStatus.CANCELLED)

    async def confirm_pending_request(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self.get_appointment_for_admin(appointment_id, staff_telegram_id)
        if appointment is None:
            raise AppointmentNotFoundError()
        self._ensure_not_finalized(appointment, _REQUEST_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(_PROPOSAL_PENDING_CLIENT_ANSWER_MESSAGE)

        await self._ensure_slot_available(appointment.doctor_id, appointment.datetime, appointment_id, appointment.client_id)

        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)
        status_updated_at = get_current_tashkent_time()
        confirmed = await self.appointment_repository.try_confirm_or_reject_pending(
            appointment_id, AppointmentStatus.CONFIRMED, acting_user_id, status_updated_at
        )
        if not confirmed:
            await self._raise_already_decided(appointment_id, _BOOKING_ALREADY_DECIDED_MESSAGE, kind="booking")

        appointment.status = AppointmentStatus.CONFIRMED
        appointment.status_updated_at = status_updated_at
        appointment.decided_by_user_id = acting_user_id

        return appointment

    async def reject_pending_request(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self.get_appointment_for_admin(appointment_id, staff_telegram_id)
        if appointment is None:
            raise AppointmentNotFoundError()
        self._ensure_not_finalized(appointment, _REQUEST_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(_PROPOSAL_PENDING_CLIENT_ANSWER_MESSAGE)

        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)
        status_updated_at = get_current_tashkent_time()
        rejected = await self.appointment_repository.try_confirm_or_reject_pending(
            appointment_id, AppointmentStatus.CANCELLED, acting_user_id, status_updated_at
        )
        if not rejected:
            await self._raise_already_decided(appointment_id, _BOOKING_ALREADY_DECIDED_MESSAGE, kind="booking")

        appointment.status = AppointmentStatus.CANCELLED
        appointment.status_updated_at = status_updated_at
        appointment.decided_by_user_id = acting_user_id

        return appointment

    async def propose_new_datetime(
        self, appointment_id: int, staff_telegram_id: int, proposed_datetime: str, kind: str
    ) -> Appointment:
        appointment = await self.get_appointment_for_admin(appointment_id, staff_telegram_id)
        if appointment is None:
            raise AppointmentNotFoundError()
        self._ensure_not_finalized(appointment, _REQUEST_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
            raise NegotiationInProgressError(_PROPOSAL_ALREADY_PENDING_MESSAGE)

        validated = validate_datetime(proposed_datetime)
        self._validate_min_lead_time(validated)

        await self._ensure_slot_available(appointment.doctor_id, validated, appointment_id, appointment.client_id)

        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)

        client = await self.user_repository.get_client_by_id(appointment.client_id)
        if client is not None and client.telegram_user_id is None:
            status_updated_at = get_current_tashkent_time()
            applied = await self.appointment_repository.try_apply_new_datetime_immediately(
                appointment_id, validated, acting_user_id, status_updated_at, appointment.status.value
            )
            if not applied:
                await self._raise_already_decided(appointment_id, _BOOKING_ALREADY_DECIDED_MESSAGE, kind=kind)

            appointment.datetime = validated
            appointment.status = AppointmentStatus.CONFIRMED
            appointment.proposed_datetime = None
            appointment.proposed_by = None
            appointment.decided_by_user_id = acting_user_id
            appointment.status_updated_at = status_updated_at

            return appointment

        status_updated_at = get_current_tashkent_time()
        proposed = await self.appointment_repository.try_propose_new_datetime(
            appointment_id, validated, acting_user_id, status_updated_at, appointment.status.value
        )
        if not proposed:
            await self._raise_already_decided(appointment_id, _BOOKING_ALREADY_DECIDED_MESSAGE, kind=kind)

        appointment.datetime = validated
        appointment.status = AppointmentStatus.PENDING
        appointment.proposed_datetime = None
        appointment.proposed_by = None
        appointment.decided_by_user_id = acting_user_id
        appointment.status_updated_at = status_updated_at

        return appointment

    async def accept_proposed_datetime(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, _REQUEST_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is None:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        if appointment.proposed_by != CreatedBy.ADMIN:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        await self._ensure_slot_available(appointment.doctor_id, appointment.proposed_datetime, appointment_id, appointment.client_id)

        status_updated_at = get_current_tashkent_time()
        accepted = await self.appointment_repository.try_resolve_admin_proposal(
            appointment_id,
            accept=True,
            status_updated_at=status_updated_at,
            new_datetime=appointment.proposed_datetime,
        )
        if not accepted:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        appointment.datetime = appointment.proposed_datetime
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.proposed_datetime = None
        appointment.proposed_by = None
        appointment.status_updated_at = status_updated_at

        return appointment

    async def reject_proposed_datetime(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, _REQUEST_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is None:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        if appointment.proposed_by != CreatedBy.ADMIN:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        status_updated_at = get_current_tashkent_time()
        rejected = await self.appointment_repository.try_resolve_admin_proposal(
            appointment_id,
            accept=False,
            status_updated_at=status_updated_at,
        )
        if not rejected:
            raise NoPendingProposalError(_NO_PENDING_PROPOSAL_MESSAGE)

        appointment.status = AppointmentStatus.CANCELLED
        appointment.proposed_datetime = None
        appointment.proposed_by = None
        appointment.status_updated_at = status_updated_at

        return appointment

    async def request_reschedule_by_client(
        self, appointment_id: int, telegram_user_id: int, new_datetime: str
    ) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, _RECORD_NO_LONGER_AVAILABLE_MESSAGE)

        is_own_pending_self_booking = (
            appointment.status == AppointmentStatus.PENDING
            and appointment.created_by == CreatedBy.CLIENT
        )
        can_negotiate = (
            appointment.status == AppointmentStatus.CONFIRMED
            or (appointment.status == AppointmentStatus.PENDING and appointment.created_by == CreatedBy.ADMIN)
        )

        if not is_own_pending_self_booking and not can_negotiate:
            raise AwaitingClinicDecisionError(_RESCHEDULE_NOT_AVAILABLE_MESSAGE)

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(_PROPOSAL_ALREADY_PENDING_MESSAGE)

        validated = validate_datetime(new_datetime)
        self._validate_min_lead_time(validated)

        if is_own_pending_self_booking:
            # Собственная ещё не решённая клиникой заявка клиента — правим datetime
            # напрямую, без согласования (клиника и так ещё ничего не подтверждала).
            await self._ensure_slot_available(appointment.doctor_id, validated, appointment_id, appointment.client_id)
            accepted = await self.appointment_repository.try_update_own_pending_datetime(appointment_id, validated)
            if not accepted:
                await self._raise_already_decided(appointment_id, _RESCHEDULE_ALREADY_DECIDED_MESSAGE, kind="reschedule")
            appointment.datetime = validated
            return appointment

        await self.appointment_repository.update_proposed_datetime(appointment_id, validated)
        await self.appointment_repository.update_proposed_by(appointment_id, CreatedBy.CLIENT)
        appointment.proposed_datetime = validated
        appointment.proposed_by = CreatedBy.CLIENT

        return appointment

    async def accept_client_reschedule(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self.get_appointment_for_admin(appointment_id, staff_telegram_id)
        if appointment is None:
            raise AppointmentNotFoundError()
        self._ensure_not_finalized(appointment, _RECORD_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_by != CreatedBy.CLIENT:
            raise NoPendingProposalError(_NO_CLIENT_PROPOSAL_MESSAGE)

        await self._ensure_slot_available(appointment.doctor_id, appointment.proposed_datetime, appointment_id, appointment.client_id)

        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)
        status_updated_at = get_current_tashkent_time()
        accepted = await self.appointment_repository.try_resolve_client_reschedule(
            appointment_id,
            accept=True,
            decided_by_user_id=acting_user_id,
            status_updated_at=status_updated_at,
            new_datetime=appointment.proposed_datetime,
        )
        if not accepted:
            await self._raise_already_decided(appointment_id, _RESCHEDULE_ALREADY_DECIDED_MESSAGE, kind="reschedule")

        appointment.datetime = appointment.proposed_datetime
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.proposed_datetime = None
        appointment.proposed_by = None
        appointment.decided_by_user_id = acting_user_id
        appointment.status_updated_at = status_updated_at

        return appointment

    async def reject_client_reschedule(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self.get_appointment_for_admin(appointment_id, staff_telegram_id)
        if appointment is None:
            raise AppointmentNotFoundError()
        self._ensure_not_finalized(appointment, _RECORD_NO_LONGER_AVAILABLE_MESSAGE)

        if appointment.proposed_by != CreatedBy.CLIENT:
            raise NoPendingProposalError(_NO_CLIENT_PROPOSAL_MESSAGE)

        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)
        status_updated_at = get_current_tashkent_time()
        rejected = await self.appointment_repository.try_resolve_client_reschedule(
            appointment_id,
            accept=False,
            decided_by_user_id=acting_user_id,
            status_updated_at=status_updated_at,
        )
        if not rejected:
            await self._raise_already_decided(appointment_id, _RESCHEDULE_ALREADY_DECIDED_MESSAGE, kind="reschedule")

        appointment.status = AppointmentStatus.CANCELLED
        appointment.proposed_datetime = None
        appointment.proposed_by = None
        appointment.decided_by_user_id = acting_user_id
        appointment.status_updated_at = status_updated_at

        return appointment

    async def update_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.appointment_repository.update_notification_message_id(appointment_id, message_id)

    async def update_admin_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.appointment_repository.update_admin_notification_message_id(appointment_id, message_id)

    async def update_proposal_message_id(self, appointment_id: int, message_id: int | None) -> None:
        await self.appointment_repository.update_proposal_message_id(appointment_id, message_id)

    async def record_notification(self, appointment_id: int, chat_id: int, message_id: int, kind: str) -> None:
        await self.appointment_repository.add_appointment_notification(appointment_id, chat_id, message_id, kind)

    async def get_invalidation_targets(
        self, appointment_id: int, kind: str, actor_chat_id: int
    ) -> list[AppointmentNotification]:
        notifications = await self.appointment_repository.get_appointment_notifications(appointment_id, kind)

        return [n for n in notifications if n.chat_id != actor_chat_id]

    async def delete_appointment(self, appointment: Appointment) -> None:
        if not await self.appointment_repository.appointment_exists(appointment.id):
            raise AppointmentNotFoundError()

        await self.appointment_repository.delete_appointment(appointment.id)

    async def update_status(self, appointment: Appointment, status: AppointmentStatus) -> Appointment:
        status_updated_at = get_current_tashkent_time()
        await self.appointment_repository.update_appointment_status(appointment.id, status, status_updated_at)
        appointment.status = status
        appointment.status_updated_at = status_updated_at

        return appointment

    async def complete_appointment_by_admin(self, appointment: Appointment, staff_telegram_id: int) -> Appointment:
        acting_user_id = await self._resolve_acting_user_id(staff_telegram_id)
        status_updated_at = get_current_tashkent_time()
        completed = await self.appointment_repository.try_complete_appointment(
            appointment.id, acting_user_id, status_updated_at
        )
        if not completed:
            await self._raise_already_decided(appointment.id, _COMPLETION_ALREADY_DECIDED_MESSAGE, kind="completion")

        appointment.status = AppointmentStatus.COMPLETED
        appointment.status_updated_at = status_updated_at
        appointment.decided_by_user_id = acting_user_id

        return appointment

    async def auto_confirm_pending(self, appointment_id: int) -> Appointment | None:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None
        if appointment.status != AppointmentStatus.PENDING or appointment.created_by != CreatedBy.ADMIN:
            return None

        status_updated_at = get_current_tashkent_time()
        await self.appointment_repository.update_appointment_status(
            appointment_id, AppointmentStatus.CONFIRMED, status_updated_at
        )
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.status_updated_at = status_updated_at

        return appointment

    async def complete_confirmed_appointment(self, appointment_id: int) -> Appointment | None:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None
        if appointment.status != AppointmentStatus.CONFIRMED or appointment.proposed_datetime is not None:
            return None

        return await self.update_status(appointment, AppointmentStatus.COMPLETED)

    async def expire_reschedule_request(self, appointment_id: int) -> Appointment | None:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None
        if appointment.proposed_datetime is None:
            return None
        # This method previously ran status-independently on purpose (to also cover
        # the PENDING+ADMIN counter-offer negotiation branch), but per product
        # decision the "your reschedule request expired" notification should not
        # fire once the appointment itself has been finalized/cancelled by either
        # side -- CONFIRMED and PENDING are the only statuses where an outstanding
        # reschedule negotiation is still meaningful.
        if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING):
            return None

        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)

        return appointment

    async def expire_pending_request(self, appointment_id: int) -> Appointment | None:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None
        if appointment.status != AppointmentStatus.PENDING:
            return None

        status_updated_at = get_current_tashkent_time()
        await self.appointment_repository.update_appointment_status(
            appointment_id, AppointmentStatus.EXPIRED, status_updated_at
        )
        appointment.status = AppointmentStatus.EXPIRED
        appointment.status_updated_at = status_updated_at

        return appointment

    async def clear_proposal_state(self, appointment_id: int) -> None:
        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposal_message_id(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)

    async def update_purpose(self, appointment: Appointment, new_purpose: str) -> Appointment:
        appointment.purpose = validate_purpose(new_purpose)
        await self.appointment_repository.update_appointment(appointment.id, appointment)

        return appointment

    async def update_price(self, appointment: Appointment, new_price: float) -> Appointment:
        appointment.price = validate_price(str(new_price))
        await self.appointment_repository.update_appointment_price(appointment.id, appointment.price)

        return appointment

    async def _resolve_client(self, phone: str) -> User:
        phone = normalize_phone(phone.strip())

        client = await self.user_repository.get_client_by_phone(phone)
        if client is None:
            raise UserNotFoundError(_CLIENT_NOT_FOUND_BY_PHONE_MESSAGE)

        return client

    async def get_appointment_with_client_info(
        self, appointment_id: int
    ) -> tuple[Appointment, User | None]:
        """Get appointment and related client info.

        Used for notification handlers. Returns appointment and client or None.
        """
        appointment = await self._get_or_raise(appointment_id)
        client = await self.user_repository.get_client_by_id(appointment.client_id)

        return appointment, client

    async def _get_or_raise(self, appointment_id: int) -> Appointment:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        return appointment

    async def _resolve_acting_user_id(self, staff_telegram_id: int) -> int:
        acting_user = await self.user_repository.get_user_by_telegram_id(staff_telegram_id)
        if acting_user is None:
            raise UserNotFoundError(_STAFF_NOT_FOUND_MESSAGE)

        return acting_user.ID

    async def _raise_already_decided(
        self, appointment_id: int, action_message: dict[str, str], kind: str
    ) -> None:
        current = await self.appointment_repository.get_appointment_by_id(appointment_id)
        decided_by_user_id = current.decided_by_user_id if current is not None else None
        label = await self.resolve_decision_label(decided_by_user_id)
        outcome_text = self.resolve_decision_outcome_text(current, kind) if current is not None else _DEFAULT_OUTCOME_TEXT
        message = {
            "ru": f"{action_message['ru']}: {label['ru']}.",
            "uz": f"{action_message['uz']}: {label['uz']}.",
        }
        raise AppointmentAlreadyDecidedError(
            message,
            decided_by_label=label,
            outcome_text=outcome_text,
            appointment=current,
        )

    def _ensure_not_finalized(self, appointment: Appointment, message: str | dict[str, str]) -> None:
        if appointment.status in (
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.EXPIRED,
        ):
            raise AppointmentAlreadyFinalizedError(message)

    def _is_within_cancellation_cutoff(self, appointment: Appointment) -> bool:
        appointment_dt = datetime.fromisoformat(appointment.datetime)
        now = get_current_tashkent_datetime()

        return appointment_dt - now < timedelta(hours=CANCELLATION_CUTOFF_HOURS)

    def _validate_min_lead_time(self, target_datetime: str) -> None:
        target_dt = datetime.fromisoformat(target_datetime)
        now = get_current_tashkent_datetime()

        if target_dt - now < MIN_LEAD_TIME:
            raise BookingTooSoonError(_BOOKING_TOO_SOON_MESSAGE)

    async def _count_pending_self_bookings(self, client_telegram_id: int) -> int:
        appointments = await self.appointment_repository.get_appointments_by_telegram_id(client_telegram_id)
        return sum(
            1 for a in appointments
            if a.created_by == CreatedBy.CLIENT and a.status == AppointmentStatus.PENDING
        )

    async def _count_recent_client_cancellations(self, client_telegram_id: int) -> int:
        appointments = await self.appointment_repository.get_appointments_by_telegram_id(client_telegram_id)
        now = get_current_tashkent_datetime()
        window = timedelta(minutes=CANCELLATION_COOLDOWN_WINDOW_MINUTES)

        count = 0
        for a in appointments:
            if a.created_by != CreatedBy.CLIENT or a.status != AppointmentStatus.CANCELLED:
                continue
            if a.status_updated_at is None:
                continue
            cancelled_at = datetime.fromisoformat(a.status_updated_at)
            if now - cancelled_at < window:
                count += 1

        return count

    async def _ensure_slot_available(
        self, doctor_id: int, datetime_str: str, exclude_appointment_id: int | None, client_id: int
    ) -> None:
        date_part = datetime_str.split(" ")[0]

        appointments = await self.appointment_repository.get_appointments_by_doctor_and_date(
            doctor_id, date_part, statuses=[AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
        )
        active_at_slot = [
            a for a in appointments
            if a.datetime == datetime_str and a.id != exclude_appointment_id
        ]

        for other in active_at_slot:
            if other.client_id == client_id:
                raise SlotUnavailableError(DUPLICATE_CLIENT_SLOT_MESSAGE)

        if MAX_BOOKINGS_PER_SLOT is None:
            if active_at_slot:
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE)
            return

        if len(active_at_slot) >= MAX_BOOKINGS_PER_SLOT:
            raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE)

    async def get_available_slots(
        self, doctor_id: int, day: date, now: datetime, exclude_appointment_id: int | None = None
    ) -> list[str]:
        slots = generate_available_slots(day, now)

        if MAX_BOOKINGS_PER_SLOT is None:
            occupying = await self.appointment_repository.get_appointments_by_doctor_and_date(
                doctor_id, day.isoformat(), statuses=[AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
            )
            booked_times = {
                appointment.datetime.split(" ")[1]
                for appointment in occupying
                if appointment.id != exclude_appointment_id
            }
            return [slot for slot in slots if slot not in booked_times]

        appointments = await self.appointment_repository.get_appointments_by_doctor_and_date(
            doctor_id, day.isoformat(), statuses=[AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
        )
        counts = Counter(
            appointment.datetime.split(" ")[1]
            for appointment in appointments
            if appointment.id != exclude_appointment_id
        )
        return [slot for slot in slots if counts[slot] < MAX_BOOKINGS_PER_SLOT]

    async def get_day_slot_occupancy(
        self, doctor_id: int, day: date, now: datetime, exclude_appointment_id: int | None = None
    ) -> list[tuple[str, list[Appointment]]]:
        """Return every generated slot for the day paired with the appointments
        occupying it (CONFIRMED or PENDING). Normally 0 or 1 occupants under the
        current single-occupant-per-slot rule, but legacy mm slots booked before
        the capacity was collapsed to 1 may still carry 2-3 -- all occupants are
        returned rather than picking one, leaving the choice to the caller."""
        slots = generate_available_slots(day, now)

        appointments = await self.appointment_repository.get_appointments_by_doctor_and_date(
            doctor_id, day.isoformat(), statuses=[AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
        )

        occupants_by_slot: dict[str, list[Appointment]] = {}
        for appointment in appointments:
            if appointment.id == exclude_appointment_id:
                continue
            slot_time = appointment.datetime.split(" ")[1]
            occupants_by_slot.setdefault(slot_time, []).append(appointment)

        return [(slot, occupants_by_slot.get(slot, [])) for slot in slots]

    async def get_working_days(self, reference_date: date, week_offset: int) -> list[date]:
        return generate_working_days(reference_date, week_offset)

    async def find_first_available_week_offset(self, reference_date: date, max_offset: int = 3) -> int:
        return _find_first_available_week_offset(reference_date, max_offset)

    async def resolve_notification_recipients(self, appointment: Appointment) -> list[User]:
        """Resolve who should receive admin/staff-facing notifications for an appointment:
        the treating doctor plus every clinic-scope admin of that clinic, deduplicated."""
        recipients: dict[int, User] = {}

        if appointment.doctor_id is not None:
            doctor = await self.user_repository.get_user_by_id(appointment.doctor_id)
            if doctor is not None and doctor.telegram_user_id is not None:
                recipients[doctor.telegram_user_id] = doctor

        staff_records = await self.staff_repository.get_staff_by_clinic_id(appointment.clinic_id)
        for staff in staff_records:
            if staff.visibility_scope != "clinic":
                continue
            admin_user = await self.user_repository.get_user_by_telegram_id(staff.telegram_user_id)
            if admin_user is not None and admin_user.telegram_user_id is not None:
                recipients[admin_user.telegram_user_id] = admin_user

        return list(recipients.values())
