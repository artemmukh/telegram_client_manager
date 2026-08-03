from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB


_APPROVE_LABEL = {
    "ru": "✅ Принять",
    "uz": "✅ Qabul qilish",
}

_REJECT_LABEL = {
    "ru": "❌ Отклонить",
    "uz": "❌ Rad etish",
}


def name_change_approval_kb(user_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=_APPROVE_LABEL.get(lang, _APPROVE_LABEL["ru"]),
                callback_data=NameChangeApprovalCB(action="approve", user_id=user_id).pack(),
            ),
            InlineKeyboardButton(
                text=_REJECT_LABEL.get(lang, _REJECT_LABEL["ru"]),
                callback_data=NameChangeApprovalCB(action="reject", user_id=user_id).pack(),
            ),
        ]
    ])
