from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.slot_blocking_cb import (
    SlotBlockCancelCB,
    SlotBlockConfirmCB,
    SlotBlockListCB,
    SlotBlockTargetCB,
)
from bot.models.blocked_slot import BlockedSlot
from bot.models.user import User
from bot.utils.pagination import get_circular_page

_CREATE_LABEL = {"ru": "➕ Создать", "uz": "➕ Yaratish"}
_MANAGE_LABEL = {"ru": "📒 Управление", "uz": "📒 Boshqarish"}
_BACK_LABEL = {"ru": "⬅️ Назад", "uz": "⬅️ Orqaga"}
_CLINIC_WIDE_LABEL = {"ru": "🏥 Вся клиника", "uz": "🏥 Butun klinika"}
_CANCEL_LABEL = {"ru": "❌ Отменить", "uz": "❌ Bekor qilish"}
_CONTINUE_LABEL = {"ru": "✅ Продолжить", "uz": "✅ Davom etish"}
_CONFIRM_LABEL = {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"}
_CANCEL_BLOCK_LABEL = {"ru": "❌ Отменить блокировку №{id}", "uz": "❌ №{id} bloklashni bekor qilish"}
_PAGE_INDICATOR_LABEL = {"ru": "{current}/{total}", "uz": "{current}/{total}"}
_YES_CANCEL_LABEL = {"ru": "✅ Да, отменить", "uz": "✅ Ha, bekor qilish"}
_NO_LABEL = {"ru": "❌ Нет", "uz": "❌ Yo'q"}


def slot_blocking_menu_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text=_CREATE_LABEL.get(lang, _CREATE_LABEL["ru"]), callback_data="slot_blocking_create")
    builder.button(text=_MANAGE_LABEL.get(lang, _MANAGE_LABEL["ru"]), callback_data="slot_blocking_manage")
    builder.button(text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def slot_blocking_target_kb(doctors: list[User], lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for doctor in doctors:
        builder.button(text=doctor.full_name, callback_data=SlotBlockTargetCB(staff_id=doctor.ID).pack())
    rows = [1] * len(doctors)

    builder.button(text=_CLINIC_WIDE_LABEL.get(lang, _CLINIC_WIDE_LABEL["ru"]), callback_data=SlotBlockTargetCB(staff_id=0).pack())
    rows.append(1)

    builder.button(text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]), callback_data="slot_blocking_menu")
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def slot_blocking_confirm_kb(lang: str = "ru", *, has_conflicts: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    confirm_label = _CONTINUE_LABEL if has_conflicts else _CONFIRM_LABEL
    builder.button(
        text=confirm_label.get(lang, confirm_label["ru"]),
        callback_data=SlotBlockConfirmCB(action="create").pack(),
    )
    builder.button(
        text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
        callback_data=SlotBlockConfirmCB(action="cancel").pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def slot_blocking_list_kb(
    blocks: list[BlockedSlot], page: int, total_pages: int, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for block in blocks:
        builder.button(
            text=_CANCEL_BLOCK_LABEL.get(lang, _CANCEL_BLOCK_LABEL["ru"]).format(id=block.id),
            callback_data=SlotBlockCancelCB(block_id=block.id, step="confirm").pack(),
        )
    rows = [1] * len(blocks)

    if total_pages > 1:
        prev_page = get_circular_page(page, total_pages, "prev")
        next_page = get_circular_page(page, total_pages, "next")

        page_text = _PAGE_INDICATOR_LABEL.get(lang, _PAGE_INDICATOR_LABEL["ru"]).format(current=page, total=total_pages)
        builder.button(text=page_text, callback_data="noop")
        builder.button(text="⬅️", callback_data=SlotBlockListCB(page=prev_page).pack())
        builder.button(text="➡️", callback_data=SlotBlockListCB(page=next_page).pack())
        rows += [1, 2]

    builder.button(text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]), callback_data="slot_blocking_menu")
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def slot_blocking_cancel_confirm_kb(block_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_YES_CANCEL_LABEL.get(lang, _YES_CANCEL_LABEL["ru"]),
        callback_data=SlotBlockCancelCB(block_id=block_id, step="execute").pack(),
    )
    builder.button(text=_NO_LABEL.get(lang, _NO_LABEL["ru"]), callback_data="slot_blocking_manage")

    builder.adjust(1, 1)
    return builder.as_markup()
