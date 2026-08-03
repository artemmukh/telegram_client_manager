from datetime import date, datetime

from bot.services.utils.date_parser import format_datetime_for_display

_NO_AVAILABLE_STAFF = {
    "ru": "В вашей клинике сейчас нет доступных врачей для записи.",
    "uz": "Sizning klinikangizda hozircha yozilish uchun mavjud shifokorlar yo'q.",
}

_CHOOSE_SPECIALIST = {
    "ru": "Выберите специалиста:",
    "uz": "Mutaxassisni tanlang:",
}

_CHOOSE_DAY = {
    "ru": "Выберите день записи:",
    "uz": "Qabul kunini tanlang:",
}

_DEFAULT_STAFF_NAME_FALLBACK = {
    "ru": "Специалист",
    "uz": "Mutaxassis",
}

_INVALID_DATE = {
    "ru": "Некорректная дата, попробуйте ещё раз.",
    "uz": "Sana noto'g'ri, qaytadan urinib ko'ring.",
}

_NO_SLOTS_FOR_DAY = {
    "ru": "На этот день больше нет доступных слотов.",
    "uz": "Bu kunga endi bo'sh vaqt yo'q.",
}

_INVALID_TIME = {
    "ru": "Некорректное время, попробуйте ещё раз.",
    "uz": "Vaqt noto'g'ri, qaytadan urinib ko'ring.",
}

_COMPLAINT_PROMPT = {
    "ru": "Опишите жалобу или причину визита (от 2 до 100 символов):",
    "uz": "Shikoyat yoki tashrif sababini yozing (2 dan 100 belgigacha):",
}

_SUBMITTED = {
    "ru": "✅ Заявка отправлена. Ожидайте подтверждения от клиники.",
    "uz": "✅ Ariza yuborildi. Klinika tasdiqlashini kuting.",
}

_BACK_TO_APPOINTMENTS_MENU = {
    "ru": "⬅️ К меню записей",
    "uz": "⬅️ Yozuvlar menyusiga",
}

_CANCEL_LABEL = {
    "ru": "❌ Отмена",
    "uz": "❌ Bekor qilish",
}

_DAY_BACK_LABEL = {
    "ru": "⬅️ Назад",
    "uz": "⬅️ Orqaga",
}

_DAY_FORWARD_LABEL = {
    "ru": "➡️ Дальше",
    "uz": "➡️ Keyingi",
}

_CONFIRM_SUBMIT_LABEL = {
    "ru": "✅ Отправить",
    "uz": "✅ Yuborish",
}

_CONFIRM_RESTART_LABEL = {
    "ru": "✏️ Изменить",
    "uz": "✏️ O'zgartirish",
}

_NO_CLINIC_INFO = {
    "ru": "Информация не доступна",
    "uz": "Ma'lumot mavjud emas",
}


def no_available_staff(lang: str = "ru") -> str:
    return _NO_AVAILABLE_STAFF.get(lang, _NO_AVAILABLE_STAFF["ru"])


def choose_specialist(lang: str = "ru") -> str:
    return _CHOOSE_SPECIALIST.get(lang, _CHOOSE_SPECIALIST["ru"])


def choose_day(lang: str = "ru") -> str:
    return _CHOOSE_DAY.get(lang, _CHOOSE_DAY["ru"])


def default_staff_name_fallback(lang: str = "ru") -> str:
    return _DEFAULT_STAFF_NAME_FALLBACK.get(lang, _DEFAULT_STAFF_NAME_FALLBACK["ru"])


def invalid_date(lang: str = "ru") -> str:
    return _INVALID_DATE.get(lang, _INVALID_DATE["ru"])


def no_slots_for_day(lang: str = "ru") -> str:
    return _NO_SLOTS_FOR_DAY.get(lang, _NO_SLOTS_FOR_DAY["ru"])


def invalid_time(lang: str = "ru") -> str:
    return _INVALID_TIME.get(lang, _INVALID_TIME["ru"])


def complaint_prompt(lang: str = "ru") -> str:
    return _COMPLAINT_PROMPT.get(lang, _COMPLAINT_PROMPT["ru"])


def submitted(lang: str = "ru") -> str:
    return _SUBMITTED.get(lang, _SUBMITTED["ru"])


def back_to_appointments_menu(lang: str = "ru") -> str:
    return _BACK_TO_APPOINTMENTS_MENU.get(lang, _BACK_TO_APPOINTMENTS_MENU["ru"])


def cancel_label(lang: str = "ru") -> str:
    return _CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"])


def day_back_label(lang: str = "ru") -> str:
    return _DAY_BACK_LABEL.get(lang, _DAY_BACK_LABEL["ru"])


def day_forward_label(lang: str = "ru") -> str:
    return _DAY_FORWARD_LABEL.get(lang, _DAY_FORWARD_LABEL["ru"])


def confirm_submit_label(lang: str = "ru") -> str:
    return _CONFIRM_SUBMIT_LABEL.get(lang, _CONFIRM_SUBMIT_LABEL["ru"])


def confirm_restart_label(lang: str = "ru") -> str:
    return _CONFIRM_RESTART_LABEL.get(lang, _CONFIRM_RESTART_LABEL["ru"])


def choose_time_prompt(day: date, lang: str = "ru") -> str:
    if lang == "uz":
        return f"{day.strftime('%d.%m.%Y')} uchun vaqtni tanlang:"

    return f"Выберите время на {day.strftime('%d.%m.%Y')}:"


def build_booking_confirmation_text(
    doctor_name: str, day: date, slot: str, complaint: str, clinic_name: str | None, lang: str = "ru"
) -> str:
    slot_time = datetime.strptime(slot, "%H:%M").time()
    display_datetime = format_datetime_for_display(datetime.combine(day, slot_time), lang)
    clinic_display = clinic_name or _NO_CLINIC_INFO.get(lang, _NO_CLINIC_INFO["ru"])

    if lang == "uz":
        return (
            "Yozuv ma'lumotlarini tekshiring:\n\n"
            f"👨‍⚕️ Mutaxassis: {doctor_name}\n"
            f"📅 Sana va vaqt: {display_datetime}\n"
            f"📝 Shikoyat: {complaint}\n"
            f"🏥 Klinika: {clinic_display}\n\n"
            "Yozilish arizasini yuborishni xohlaysizmi?"
        )

    return (
        "Проверьте данные записи:\n\n"
        f"👨‍⚕️ Специалист: {doctor_name}\n"
        f"📅 Дата и время: {display_datetime}\n"
        f"📝 Жалоба: {complaint}\n"
        f"🏥 Клиника: {clinic_display}\n\n"
        "Отправить заявку на запись?"
    )
