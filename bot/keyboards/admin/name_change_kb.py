from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB


def name_change_approval_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принять",
                callback_data=NameChangeApprovalCB(action="approve", user_id=user_id).pack(),
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=NameChangeApprovalCB(action="reject", user_id=user_id).pack(),
            ),
        ]
    ])
