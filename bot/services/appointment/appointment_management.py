from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.user_exceptions import UserNotFoundError, PhoneAlreadyExistsError
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_datetime, validate_purpose, validate_full_name, validate_phone, FULL_NAME_PATTERN


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
