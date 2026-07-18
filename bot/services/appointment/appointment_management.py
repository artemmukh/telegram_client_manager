from datetime import date, datetime, timedelta

from bot.config.booking_config import MAX_PENDING_REQUESTS_PER_CLIENT
from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    AwaitingClinicDecisionError,
    BookingTooSoonError,
    CancellationWindowExpiredError,
    NegotiationInProgressError,
    NoPendingProposalError,
    PendingRequestLimitExceededError,
    SlotUnavailableError,
)
from bot.exceptions.user_exceptions import UserNotFoundError, PhoneAlreadyExistsError
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import get_current_tashkent_time, get_current_tashkent_datetime
from bot.services.utils.slot_helpers import generate_available_slots
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_datetime, validate_price, validate_purpose, validate_full_name, \
    validate_phone, SEARCH_NAME_PATTERN

CANCELLATION_CUTOFF_HOURS = 1
MIN_LEAD_TIME = timedelta(hours=2, minutes=30)


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
            raise UserNotFoundError("Врач не найден.")

        doctor_id = admin.ID
        if data.get("staff_user_id") is not None:
            doctor = await self.user_repository.get_user_by_id(data["staff_user_id"])
            if doctor is None:
                raise UserNotFoundError("Врач не найден.")
            if doctor.clinic_id != clinic.clinic_id:
                raise UserNotFoundError("Врач не найден.")
            doctor_id = doctor.ID

        await self._ensure_slot_available(doctor_id, appointment_datetime, None)

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
            created_by_telegram_id=doctor_telegram_id,
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
            raise UserNotFoundError("Клиент не найден или не привязан к клинике.")

        return await self.list_clinic_doctors(client.clinic_id)

    async def list_clinic_doctors_for_creation(self, admin_telegram_id: int) -> list[User]:
        clinic = await self.get_admin_clinic(admin_telegram_id)
        staff_record = await self.staff_repository.get_staff(admin_telegram_id)

        if staff_record is None or staff_record.visibility_scope in (None, "own"):
            return []

        return await self.list_clinic_doctors(clinic.clinic_id)

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
            raise UserNotFoundError("Клиент не найден.")

        await self.ensure_pending_limit_not_exceeded(client_telegram_id)

        staff = await self.user_repository.get_user_by_id(data["staff_user_id"])
        if staff is None:
            raise UserNotFoundError("Специалист не найден.")

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        self._validate_min_lead_time(appointment_datetime)
        purpose = validate_purpose(data["complaint"])

        await self._ensure_slot_available(staff.ID, appointment_datetime, None)

        appointment = Appointment(
            clinic_id=client.clinic_id,
            client_id=client.ID,
            doctor_id=staff.ID,
            datetime=appointment_datetime,
            purpose=purpose,
            created_by=CreatedBy.CLIENT,
            status=AppointmentStatus.PENDING,
            clinic_name=client.clinic_name,
            created_by_telegram_id=staff.telegram_user_id,
            created_at=get_current_tashkent_time(),
        )

        return await self.appointment_repository.create_appointment(appointment)

    async def ensure_pending_limit_not_exceeded(self, client_telegram_id: int) -> None:
        pending_count = await self._count_pending_self_bookings(client_telegram_id)
        if pending_count >= MAX_PENDING_REQUESTS_PER_CLIENT:
            raise PendingRequestLimitExceededError(
                "У вас уже есть заявка на рассмотрении. Дождитесь решения клиники, прежде чем создавать новую."
            )

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

    async def confirm_appointment_by_client(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(
            appointment,
            "Эта запись больше недоступна для подтверждения. "
            "Возможно, она была отменена или уже завершена. Обновите список записей.",
        )

        if appointment.created_by == CreatedBy.CLIENT and appointment.status == AppointmentStatus.PENDING:
            raise AwaitingClinicDecisionError("Дождитесь решения клиники по вашей заявке.")

        await self._ensure_slot_available(appointment.doctor_id, appointment.datetime, appointment_id)

        return await self.update_status(appointment_id, AppointmentStatus.CONFIRMED)

    async def cancel_appointment_by_client(
        self, appointment_id: int, telegram_user_id: int, enforce_cutoff: bool = True
    ) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(
            appointment,
            "Эта запись больше недоступна для отмены. "
            "Возможно, она уже была отменена или завершена. Обновите список записей.",
        )

        if enforce_cutoff and self._is_within_cancellation_cutoff(appointment):
            raise CancellationWindowExpiredError(
                "Отмена возможна не позднее чем за 1 час, свяжитесь с клиникой"
            )

        if appointment.proposed_datetime is not None:
            await self.appointment_repository.update_proposed_datetime(appointment_id, None)
            await self.appointment_repository.update_proposed_by(appointment_id, None)

        return await self.update_status(appointment_id, AppointmentStatus.CANCELLED)

    async def confirm_pending_request(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        self._ensure_not_finalized(appointment, "Эта заявка больше недоступна.")

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(
                "По этой заявке уже предложено новое время. Дождитесь ответа клиента."
            )

        await self._ensure_slot_available(appointment.doctor_id, appointment.datetime, appointment_id)

        return await self.update_status(appointment_id, AppointmentStatus.CONFIRMED)

    async def reject_pending_request(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        self._ensure_not_finalized(appointment, "Эта заявка больше недоступна.")

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(
                "По этой заявке уже предложено новое время. Дождитесь ответа клиента."
            )

        return await self.update_status(appointment_id, AppointmentStatus.CANCELLED)

    async def propose_new_datetime(
        self, appointment_id: int, staff_telegram_id: int, proposed_datetime: str
    ) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        self._ensure_not_finalized(appointment, "Эта заявка больше недоступна.")

        if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
            raise NegotiationInProgressError(
                "По этой записи уже есть предложение, ожидающее ответа."
            )

        validated = validate_datetime(proposed_datetime)
        self._validate_min_lead_time(validated)

        await self._ensure_slot_available(appointment.doctor_id, validated, appointment_id)

        await self.appointment_repository.update_proposed_datetime(appointment_id, validated)
        await self.appointment_repository.update_proposed_by(appointment_id, CreatedBy.ADMIN)
        appointment.proposed_datetime = validated
        appointment.proposed_by = CreatedBy.ADMIN

        return appointment

    async def accept_proposed_datetime(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, "Эта заявка больше недоступна.")

        if appointment.proposed_datetime is None:
            raise NoPendingProposalError("По этой записи нет предложенного времени, ожидающего ответа.")

        if appointment.proposed_by != CreatedBy.ADMIN:
            raise NoPendingProposalError("По этой записи нет предложенного времени, ожидающего ответа.")

        await self._ensure_slot_available(appointment.doctor_id, appointment.proposed_datetime, appointment_id)

        appointment.datetime = appointment.proposed_datetime
        appointment.status = AppointmentStatus.CONFIRMED
        await self.appointment_repository.update_appointment(appointment_id, appointment)

        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)
        appointment.proposed_datetime = None
        appointment.proposed_by = None

        return appointment

    async def reject_proposed_datetime(self, appointment_id: int, telegram_user_id: int) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, "Эта заявка больше недоступна.")

        if appointment.proposed_datetime is None:
            raise NoPendingProposalError("По этой записи нет предложенного времени, ожидающего ответа.")

        if appointment.proposed_by != CreatedBy.ADMIN:
            raise NoPendingProposalError("По этой записи нет предложенного времени, ожидающего ответа.")

        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)

        return await self.update_status(appointment_id, AppointmentStatus.CANCELLED)

    async def request_reschedule_by_client(
        self, appointment_id: int, telegram_user_id: int, new_datetime: str
    ) -> Appointment:
        appointment = await self.get_appointment_for_client(appointment_id, telegram_user_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        self._ensure_not_finalized(appointment, "Эта запись больше недоступна.")

        is_own_pending_self_booking = (
            appointment.status == AppointmentStatus.PENDING
            and appointment.created_by == CreatedBy.CLIENT
        )
        can_negotiate = (
            appointment.status == AppointmentStatus.CONFIRMED
            or (appointment.status == AppointmentStatus.PENDING and appointment.created_by == CreatedBy.ADMIN)
        )

        if not is_own_pending_self_booking and not can_negotiate:
            raise AwaitingClinicDecisionError(
                "Перенос доступен только для подтверждённых записей, ещё не решённых "
                "клиникой записей или собственных заявок на самозапись, ожидающих решения клиники."
            )

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(
                "По этой записи уже есть предложение, ожидающее ответа."
            )

        validated = validate_datetime(new_datetime)
        self._validate_min_lead_time(validated)

        if is_own_pending_self_booking:
            # Собственная ещё не решённая клиникой заявка клиента — правим datetime
            # напрямую, без согласования (клиника и так ещё ничего не подтверждала).
            appointment.datetime = validated
            await self.appointment_repository.update_appointment(appointment_id, appointment)
            return appointment

        await self.appointment_repository.update_proposed_datetime(appointment_id, validated)
        await self.appointment_repository.update_proposed_by(appointment_id, CreatedBy.CLIENT)
        appointment.proposed_datetime = validated
        appointment.proposed_by = CreatedBy.CLIENT

        return appointment

    async def accept_client_reschedule(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        self._ensure_not_finalized(appointment, "Эта запись больше недоступна.")

        if appointment.proposed_by != CreatedBy.CLIENT:
            raise NoPendingProposalError("Нет предложения от клиента, ожидающего решения.")

        await self._ensure_slot_available(appointment.doctor_id, appointment.proposed_datetime, appointment_id)

        appointment.datetime = appointment.proposed_datetime
        appointment.status = AppointmentStatus.CONFIRMED
        await self.appointment_repository.update_appointment(appointment_id, appointment)

        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)
        appointment.proposed_datetime = None
        appointment.proposed_by = None

        return appointment

    async def reject_client_reschedule(self, appointment_id: int, staff_telegram_id: int) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        self._ensure_not_finalized(appointment, "Эта запись больше недоступна.")

        if appointment.proposed_by != CreatedBy.CLIENT:
            raise NoPendingProposalError("Нет предложения от клиента, ожидающего решения.")

        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)

        return await self.update_status(appointment_id, AppointmentStatus.CANCELLED)

    async def update_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.appointment_repository.update_notification_message_id(appointment_id, message_id)

    async def update_admin_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.appointment_repository.update_admin_notification_message_id(appointment_id, message_id)

    async def update_proposal_message_id(self, appointment_id: int, message_id: int | None) -> None:
        await self.appointment_repository.update_proposal_message_id(appointment_id, message_id)

    async def delete_appointment(self, appointment_id: int) -> None:
        if not await self.appointment_repository.appointment_exists(appointment_id):
            raise AppointmentNotFoundError()

        await self.appointment_repository.delete_appointment(appointment_id)

    async def update_status(self, appointment_id: int, status: AppointmentStatus) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)

        status_updated_at = get_current_tashkent_time()
        await self.appointment_repository.update_appointment_status(appointment_id, status, status_updated_at)
        appointment.status = status
        appointment.status_updated_at = status_updated_at

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

    async def expire_reschedule_request(self, appointment_id: int) -> Appointment | None:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            return None
        if appointment.proposed_datetime is None:
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

    async def update_datetime(self, appointment_id: int, new_datetime: str) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)

        appointment.datetime = validate_datetime(new_datetime)
        await self.appointment_repository.update_appointment(appointment_id, appointment)

        return appointment

    async def update_purpose(self, appointment_id: int, new_purpose: str) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)

        appointment.purpose = validate_purpose(new_purpose)
        await self.appointment_repository.update_appointment(appointment_id, appointment)

        return appointment

    async def update_price(self, appointment_id: int, new_price: float) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)

        appointment.price = validate_price(str(new_price))
        await self.appointment_repository.update_appointment_price(appointment_id, appointment.price)

        return appointment

    async def _resolve_client(self, phone: str) -> User:
        phone = normalize_phone(phone.strip())

        client = await self.user_repository.get_client_by_phone(phone)
        if client is None:
            raise UserNotFoundError(
                "Клиент с таким номером не найден. Сначала создайте клиента."
            )

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

    def _ensure_not_finalized(self, appointment: Appointment, message: str) -> None:
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
            raise BookingTooSoonError(
                "Время записи должно быть не менее чем через 2 часа от текущего момента, "
                "свяжитесь с клиникой."
            )

    async def _count_pending_self_bookings(self, client_telegram_id: int) -> int:
        appointments = await self.appointment_repository.get_appointments_by_telegram_id(client_telegram_id)
        return sum(
            1 for a in appointments
            if a.created_by == CreatedBy.CLIENT and a.status == AppointmentStatus.PENDING
        )

    async def _ensure_slot_available(
        self, doctor_id: int, datetime_str: str, exclude_appointment_id: int | None
    ) -> None:
        date_part = datetime_str.split(" ")[0]
        confirmed = await self.appointment_repository.get_appointments_by_doctor_and_date(doctor_id, date_part)
        for other in confirmed:
            if other.datetime == datetime_str and other.id != exclude_appointment_id:
                raise SlotUnavailableError("Это время уже занято другой подтверждённой записью, выберите другое.")

    async def get_available_slots(self, doctor_id: int, day: date, now: datetime) -> list[str]:
        slots = generate_available_slots(day, now)
        confirmed = await self.appointment_repository.get_appointments_by_doctor_and_date(doctor_id, day.isoformat())
        booked_times = {appointment.datetime.split(" ")[1] for appointment in confirmed}

        return [slot for slot in slots if slot not in booked_times]

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
