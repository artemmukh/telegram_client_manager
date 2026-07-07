from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message

from bot.exceptions.user_exceptions import ValidationError, InvalidFullNameError
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus
from bot.validators.validators import (
    validate_client_name,
    validate_purpose,
)

STATUS_LABELS = {
    AppointmentStatus.PENDING: "Ожидает",
    AppointmentStatus.CONFIRMED: "Подтверждена",
    AppointmentStatus.CANCELLED: "Отменена",
    AppointmentStatus.COMPLETED: "Завершена",
    AppointmentStatus.NO_SHOW: "Неявка",
}


def build_appointment_confirmation(data: dict) -> str:
    display_datetime = data.get('appointment_datetime_display') or data.get('appointment_datetime', '')
    return "\n".join([
        "Проверьте данные записи:",
        "",
        f"Клиника: {data.get('clinic_name', '')}",
        f"Имя клиента: {data.get('client_name', '')}",
        f"Телефон: {data.get('phone', '')}",
        f"Дата и время: {display_datetime}",
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
    try:
        name = validate_client_name(message.text)
    except InvalidFullNameError as e:
        await message.answer(str(e))
        return False

    await state.update_data(client_name=name)
    await state.set_state(next_state)
    return True


async def datetime_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    from bot.exceptions.user_exceptions import ValidationError
    from bot.services.date_parser import parse_ru_datetime, format_datetime_for_display, format_datetime_for_db

    parsed_dt = parse_ru_datetime(message.text.strip())

    if parsed_dt is None:
        await message.answer(
            "Не смог распознать дату и время.\n"
            "Попробуйте снова:\n"
            "• завтра в 3 часа\n"
            "• 13 сентября 15:30\n"
            "• в понедельник в 14:00"
        )
        return False

    await state.update_data(
        appointment_datetime_parsed=parsed_dt,
        appointment_datetime_display=format_datetime_for_display(parsed_dt)
    )
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
