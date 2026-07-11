from datetime import datetime, timedelta

from bot.config.booking_config import MAX_PENDING_REQUESTS_PER_CLIENT
from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    AwaitingClinicDecisionError,
    CancellationWindowExpiredError,
    NegotiationInProgressError,
    NoPendingProposalError,
    PendingRequestLimitExceededError,
)
from bot.exceptions.user_exceptions import UserNotFoundError, PhoneAlreadyExistsError
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import get_current_tashkent_time, get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_datetime, validate_purpose, validate_full_name, validate_phone, FULL_NAME_PATTERN

CANCELLATION_CUTOFF_HOURS = 2


class AppointmentManagement:
    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
        clinic_repository: ClinicRepository,
        client_management=None,
    ):
        self.appointment_repository = appointment_repository
        self.user_repository = user_repository
        self.staff_repository = staff_repository
        self.clinic_repository = clinic_repository
        self.client_management = client_management

    async def create_appointment(self, doctor_telegram_id: int, data: dict) -> Appointment:
        clinic = await self.get_admin_clinic(doctor_telegram_id)

        client = await self._resolve_client(data["phone"])

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        purpose = validate_purpose(data["purpose"])

        admin = await self.user_repository.get_user_by_telegram_id(doctor_telegram_id)

        appointment = Appointment(
            clinic_id=clinic.clinic_id,
            client_id=client.ID,
            doctor_id=admin.ID if admin else None,
            datetime=appointment_datetime,
            purpose=purpose,
            created_by=CreatedBy.ADMIN,
            status=AppointmentStatus.PENDING,
            clinic_name=clinic.name,
            created_by_telegram_id=doctor_telegram_id,
            created_at=get_current_tashkent_time(),
        )

        return await self.appointment_repository.create_appointment(appointment)

    async def list_bookable_staff(self, client_telegram_id: int) -> list[User]:
        client = await self.user_repository.get_user_by_telegram_id(client_telegram_id)
        if client is None or client.clinic_id is None:
            raise UserNotFoundError("Клиент не найден или не привязан к клинике.")

        return await self.user_repository.get_staff_users_by_clinic_id(client.clinic_id)

    async def create_self_booking(self, client_telegram_id: int, data: dict) -> Appointment:
        client = await self.user_repository.get_user_by_telegram_id(client_telegram_id)
        if client is None:
            raise UserNotFoundError("Клиент не найден.")

        await self.ensure_pending_limit_not_exceeded(client_telegram_id)

        staff = await self.user_repository.get_user_by_id(data["staff_user_id"])
        if staff is None:
            raise UserNotFoundError("Специалист не найден.")

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        purpose = validate_purpose(data["complaint"])

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

    async def find_client_by_phone(self, phone: str) -> User | None:
        """Find existing client by phone. Returns None if not found."""
        phone = normalize_phone(phone.strip())
        return await self.user_repository.get_client_by_phone(phone)

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
            return client

        if self.client_management:
            return await self.client_management.create_client(
                admin_telegram_id,
                {"full_name": full_name, "phone": phone}
            )
        else:
            # Fallback: inline creation if ClientManagement not injected
            # This shouldn't happen in production
            full_name = full_name.strip()
            validate_full_name(full_name, FULL_NAME_PATTERN)
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
            )

            await self.user_repository.create_user(new_client)

            return new_client

    async def search_appointments(self, data: dict) -> list[Appointment]:
        phone = data.get("phone")
        full_name = data.get("full_name")

        if phone:
            phone = normalize_phone(phone.strip())

            client = await self.user_repository.get_client_by_phone(phone)
            if client is None:
                raise UserNotFoundError("Клиент не был найден.")

            appointments = await self.appointment_repository.get_appointments_by_client_id(client.ID)
            if not appointments:
                raise AppointmentNotFoundError("У клиента нет записей.")

            return appointments

        if full_name:
            full_name = full_name.strip()

            clients = await self.user_repository.get_clients_by_name(full_name)
            if not clients:
                raise UserNotFoundError("Клиент не был найден.")

            client_ids = [client.ID for client in clients]
            appointments = await self.appointment_repository.get_appointments_by_client_ids(client_ids)

            if not appointments:
                raise AppointmentNotFoundError("У найденных клиентов нет записей.")

            return appointments

        raise AppointmentNotFoundError("Укажите телефон или фамилию для поиска.")

    async def get_all_appointments(self) -> list[Appointment]:
        return await self.appointment_repository.get_all_appointments()

    async def get_appointment_by_id(self, appointment_id: int) -> Appointment | None:
        return await self.appointment_repository.get_appointment_by_id(appointment_id)

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
                "Отмена возможна не позднее чем за 2 часа, свяжитесь с клиникой"
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

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(
                "По этой записи уже есть предложение, ожидающее ответа."
            )

        validated = validate_datetime(proposed_datetime)
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

        if appointment.status != AppointmentStatus.CONFIRMED:
            raise AwaitingClinicDecisionError("Перенос доступен только для подтверждённых записей.")

        if appointment.proposed_datetime is not None:
            raise NegotiationInProgressError(
                "По этой записи уже есть предложение, ожидающее ответа."
            )

        validated = validate_datetime(new_datetime)

        if self._is_new_datetime_within_cutoff(validated):
            raise CancellationWindowExpiredError(
                "Новое время должно быть не менее чем через 2 часа от текущего момента, "
                "свяжитесь с клиникой."
            )

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

        appointment.datetime = appointment.proposed_datetime
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

        # Unlike reject_pending_request (2b), rejecting a client's reschedule request
        # is not terminal: the appointment stays CONFIRMED at its original datetime,
        # only the outstanding proposal is cleared.
        await self.appointment_repository.update_proposed_datetime(appointment_id, None)
        await self.appointment_repository.update_proposed_by(appointment_id, None)
        appointment.proposed_datetime = None
        appointment.proposed_by = None

        return appointment

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

        await self.appointment_repository.update_appointment_status(appointment_id, status)
        appointment.status = status

        return appointment

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

    def _is_new_datetime_within_cutoff(self, new_datetime: str) -> bool:
        new_dt = datetime.fromisoformat(new_datetime)
        now = get_current_tashkent_datetime()

        return new_dt - now < timedelta(hours=CANCELLATION_CUTOFF_HOURS)

    async def _count_pending_self_bookings(self, client_telegram_id: int) -> int:
        appointments = await self.appointment_repository.get_appointments_by_telegram_id(client_telegram_id)
        return sum(
            1 for a in appointments
            if a.created_by == CreatedBy.CLIENT and a.status == AppointmentStatus.PENDING
        )
