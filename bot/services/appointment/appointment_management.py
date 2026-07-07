from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.user_exceptions import RoleError, UserNotFoundError
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_datetime, validate_purpose


class AppointmentManagement:
    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
    ):
        self.appointment_repository = appointment_repository
        self.user_repository = user_repository
        self.staff_repository = staff_repository

    async def create_appointment(self, doctor_telegram_id: int, data: dict) -> Appointment:
        staff = await self.staff_repository.get_staff(doctor_telegram_id)
        if staff is None:
            raise RoleError("Только сотрудник клиники может создавать записи.")

        client = await self._resolve_client(data["phone"])

        appointment_datetime = validate_datetime(data["appointment_datetime"])
        purpose = validate_purpose(data["purpose"])

        appointment = Appointment(
            clinic_id=staff.clinic_id,
            client_id=client.ID,
            datetime=appointment_datetime,
            purpose=purpose,
            created_by=CreatedBy.ADMIN,
            status=AppointmentStatus.PENDING,
        )

        await self.appointment_repository.create_appointment(appointment)
        return appointment

    async def search_appointments(self, phone: str) -> list[Appointment]:
        client = await self._resolve_client(phone)

        appointments = await self.appointment_repository.get_appointments_by_client_id(client.ID)
        if not appointments:
            raise AppointmentNotFoundError("У клиента нет записей.")

        return appointments

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

    async def _get_or_raise(self, appointment_id: int) -> Appointment:
        appointment = await self.appointment_repository.get_appointment_by_id(appointment_id)
        if appointment is None:
            raise AppointmentNotFoundError()

        return appointment
