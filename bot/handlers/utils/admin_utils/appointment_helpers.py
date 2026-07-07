from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message

from bot.exceptions.user_exceptions import ValidationError
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus
from bot.validators.validators import validate_datetime, validate_purpose

STATUS_LABELS = {
    AppointmentStatus.PENDING: "Ожидает",
    AppointmentStatus.CONFIRMED: "Подтверждена",
    AppointmentStatus.CANCELLED: "Отменена",
    AppointmentStatus.COMPLETED: "Завершена",
    AppointmentStatus.NO_SHOW: "Неявка",
}


def build_appointment_confirmation(data: dict) -> str:
    return "\n".join([
        "Проверьте данные записи:",
        "",
        f"Клиника: {data.get('clinic_name', '')}",
        f"Имя клиента: {data.get('client_name', '')}",
        f"Телефон: {data.get('phone', '')}",
        f"Дата и время: {data.get('appointment_datetime', '')}",
        f"Услуга: {data.get('purpose', '')}",
        "Статус: Ожидает",
    ])


def build_appointment_card(appointment: Appointment) -> str:
    lines = [f"Запись №{appointment.id}"]

    if appointment.clinic_name:
        lines.append(f"Клиника: {appointment.clinic_name}")

    lines += [
        f"Дата и время: {appointment.datetime}",
        f"Услуга: {appointment.purpose}",
        f"Статус: {STATUS_LABELS.get(appointment.status, appointment.status.value)}",
    ]
    return "\n".join(lines)


async def show_appointments_list(message: Message, phone: str, appointments: list[Appointment]) -> None:
    lines = [f"Записи по номеру {phone} (всего: {len(appointments)}):", ""]

    for appointment in appointments:
        lines.append(build_appointment_card(appointment))
        lines.append("")

    await message.answer("\n".join(lines).strip(), reply_markup=back_to_records_kb())


async def show_appointments_with_actions(
    message: Message,
    phone: str,
    appointments: list[Appointment],
    keyboard_factory,
) -> None:
    await message.answer(f"Записи по номеру {phone} (всего: {len(appointments)}):")

    for appointment in appointments:
        await message.answer(
            build_appointment_card(appointment),
            reply_markup=keyboard_factory(appointment.id),
        )


async def client_name_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    name = message.text.strip()

    if not name:
        await message.answer("Введите имя клиента.")
        return False

    await state.update_data(client_name=name)
    await state.set_state(next_state)
    return True


async def datetime_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    try:
        value = validate_datetime(message.text.strip())
    except ValidationError as e:
        await message.answer(str(e))
        return False

    await state.update_data(appointment_datetime=value)
    await state.set_state(next_state)
    return True


async def purpose_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    try:
        value = validate_purpose(message.text.strip())
    except ValidationError as e:
        await message.answer(str(e))
        return False

    await state.update_data(purpose=value)
    await state.set_state(next_state)
    return True
