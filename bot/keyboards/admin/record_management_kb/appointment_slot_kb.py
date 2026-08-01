from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.models.appointment import Appointment


def appointment_slot_grid_kb(
    slot_occupancy: list[tuple[str, list[Appointment]]],
    cancel_callback_data: str = "admin_book_back_to_day",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for slot, occupants in slot_occupancy:
        if occupants:
            builder.button(
                text=f"🔒 {slot}",
                callback_data=AdminOccupiedSlotCB(appointment_id=occupants[0].id).pack(),
            )
        else:
            builder.button(text=slot, callback_data=ClientBookSlotCB(slot=slot).pack())

    rows = [4] * (len(slot_occupancy) // 4)
    if len(slot_occupancy) % 4:
        rows.append(len(slot_occupancy) % 4)

    builder.button(text="❌ Отмена", callback_data=cancel_callback_data)
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def occupied_slot_card_kb(back_callback_data: str = "admin_book_back_to_slots") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к слотам", callback_data=back_callback_data)
    builder.adjust(1)
    return builder.as_markup()
