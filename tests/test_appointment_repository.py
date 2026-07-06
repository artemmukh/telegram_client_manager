import aiosqlite
import pytest
import pytest_asyncio

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


@pytest_asyncio.fixture
async def appointment_setup(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    await connection.execute("PRAGMA foreign_keys = ON")

    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
    await appointment_repo.init()

    await user_repo.create_user(
        User(
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    user = await user_repo.get_user_by_telegram_id(1001)

    yield appointment_repo, user

    await connection.close()


def _appointment(client_id: int) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-01 10:00",
        purpose="Consultation",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_creates_and_reads_appointment(appointment_setup):
    appointment_repo, user = appointment_setup

    await appointment_repo.create_appointment(_appointment(user.ID))

    by_client = await appointment_repo.get_appointments_by_client_id(user.ID)
    by_telegram = await appointment_repo.get_appointments_by_telegram_id(1001)
    by_id = await appointment_repo.get_appointment_by_id(by_client[0].id)

    assert len(by_client) == 1
    assert by_client[0].purpose == "Consultation"
    assert by_client[0].status is AppointmentStatus.PENDING
    assert by_client[0].created_by is CreatedBy.ADMIN
    assert by_telegram == by_client
    assert by_id == by_client[0]
    assert await appointment_repo.appointment_exists(by_client[0].id) is True


@pytest.mark.asyncio
async def test_updates_appointment_status(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID))[0].id

    await appointment_repo.update_appointment_status(appointment_id, AppointmentStatus.CONFIRMED)

    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_deletes_appointment(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID))[0].id

    await appointment_repo.delete_appointment(appointment_id)

    assert await appointment_repo.get_appointment_by_id(appointment_id) is None
    assert await appointment_repo.appointment_exists(appointment_id) is False
