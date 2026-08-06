import logging
from datetime import datetime

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.keyboards.admin.record_management_kb.booking_request_kb import booking_request_kb
from bot.keyboards.admin.record_management_kb.completion_followup_kb import completion_followup_kb
from bot.keyboards.admin.record_management_kb.reschedule_request_kb import reschedule_request_kb
from bot.keyboards.client.appointment_response_kb import (
    appointment_invite_kb,
    appointment_reminder_details_kb,
    appointment_reminder_with_buttons_kb,
    reschedule_proposal_kb,
)
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.date_parser import (
    build_reschedule_proposal_line,
    format_datetime_for_display,
    reschedule_negotiation_note,
)
from bot.services.utils.escape_html import escape_html
from bot.services.utils.telegram_notifier import TelegramNotifier
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, status_label

logger = logging.getLogger(__name__)

_REMINDER_TEXT = {
    "ru": (
        "Напоминаем вам о записи.\n\n"
        "📱 Номер: {phone}\n"
        "🏥 Услуга: {purpose}\n"
        "📅 Дата и время: {datetime}"
    ),
    "uz": (
        "Sizga qabul haqida eslatib o'tamiz.\n\n"
        "📱 Raqam: {phone}\n"
        "🏥 Xizmat: {purpose}\n"
        "📅 Sana va vaqt: {datetime}"
    ),
}

_APPOINTMENT_CANCELLED_BY_ADMIN = {
    "ru": "❌ Ваша запись отменена администратором.\n\n👨‍⚕️ Врач: {doctor_full_name}\n📱 Номер: {doctor_phone}",
    "uz": "❌ Sizning yozuvingiz administrator tomonidan bekor qilindi.\n\n👨‍⚕️ Shifokor: {doctor_full_name}\n📱 Raqam: {doctor_phone}",
}

_APPOINTMENT_CANCELLED_BY_ADMIN_REASON = {
    "ru": "\n\nПричина: {reason}",
    "uz": "\n\nSabab: {reason}",
}

_BOOKING_REQUEST_REJECTED = {
    "ru": "❌ Клиника отклонила вашу заявку на запись.",
    "uz": "❌ Klinika sizning yozilish arizangizni rad etdi.",
}

_APPOINTMENT_CHANGED = {
    "ru": "✏️ Детали вашей записи изменены администратором\n\nДата и время: {datetime}\nУслуга: {purpose}",
    "uz": "✏️ Yozuvingiz tafsilotlari administrator tomonidan o'zgartirildi\n\nSana va vaqt: {datetime}\nXizmat: {purpose}",
}

_ADMIN_UPCOMING_APPOINTMENT = {
    "ru": (
        "📌 Предстоящая запись:\n\n"
        "👤 Клиент: {client_name}\n"
        "📱 Номер: {client_phone}\n"
        "📅 Дата и время: {datetime}\n"
        "🏥 Услуга: {purpose}"
    ),
    "uz": (
        "📌 Yaqinlashib kelayotgan yozuv:\n\n"
        "👤 Mijoz: {client_name}\n"
        "📱 Raqam: {client_phone}\n"
        "📅 Sana va vaqt: {datetime}\n"
        "🏥 Xizmat: {purpose}"
    ),
}

_ADMIN_CANCELLATION = {
    "ru": "Клиент {client_name} отменил запись.\n\n📱 Номер: {client_phone}\n📅 Дата и время: {datetime}\n🏥 Услуга: {purpose}",
    "uz": "Mijoz {client_name} yozuvni bekor qildi.\n\n📱 Raqam: {client_phone}\n📅 Sana va vaqt: {datetime}\n🏥 Xizmat: {purpose}",
}

DEFAULT_UNKNOWN_CLIENT_LABEL = {
    "ru": "Клиент",
    "uz": "Mijoz",
}

_STAFF_APPOINTMENT_CANCELLED = {
    "ru": "❌ Запись клиента {client_name} отменена ({actor}).\n\n📱 Номер: {client_phone}\n📅 Дата и время: {datetime}\n🏥 Услуга: {purpose}",
    "uz": "❌ Mijoz {client_name} yozuvi bekor qilindi ({actor}).\n\n📱 Raqam: {client_phone}\n📅 Sana va vaqt: {datetime}\n🏥 Xizmat: {purpose}",
}

_STAFF_APPOINTMENT_DELETED = {
    "ru": "🗑 Запись клиента {client_name} удалена ({actor}).\n\n📱 Номер: {client_phone}\n📅 Дата и время: {datetime}\n🏥 Услуга: {purpose}",
    "uz": "🗑 Mijoz {client_name} yozuvi o'chirildi ({actor}).\n\n📱 Raqam: {client_phone}\n📅 Sana va vaqt: {datetime}\n🏥 Xizmat: {purpose}",
}

_STAFF_APPOINTMENT_CREATED = {
    "ru": "🆕 Создана новая запись клиента {client_name} ({actor}).\n\n📱 Номер: {client_phone}\n👨‍⚕️ Врач: {doctor_full_name}\n📅 Дата и время: {datetime}\n🏥 Услуга: {purpose}",
    "uz": "🆕 Mijoz {client_name} uchun yangi yozuv yaratildi ({actor}).\n\n📱 Raqam: {client_phone}\n👨‍⚕️ Shifokor: {doctor_full_name}\n📅 Sana va vaqt: {datetime}\n🏥 Xizmat: {purpose}",
}

_ADMIN_CLIENT_CHANGED_TIME = {
    "ru": "🕐 Клиент {client_name} изменил время заявки.\n📱 Номер: {client_phone}\n📅 Новое время: {datetime}",
    "uz": "🕐 Mijoz {client_name} ariza vaqtini o'zgartirdi.\n📱 Raqam: {client_phone}\n📅 Yangi vaqt: {datetime}",
}

_ADMIN_CONFIRMATION = {
    "ru": "Клиент {client_name} подтвердил запись.\n\n📱 Номер: {client_phone}\n📅 Дата и время: {datetime}\n🏥 Услуга: {purpose}",
    "uz": "Mijoz {client_name} yozuvni tasdiqladi.\n\n📱 Raqam: {client_phone}\n📅 Sana va vaqt: {datetime}\n🏥 Xizmat: {purpose}",
}

_ADMIN_COMPLETION_PROMPT = {
    "ru": "Приём №{appointment_id} отмечен как завершённый. Открыть запись для правок (статус/услуга/цена)?",
    "uz": "№{appointment_id} qabul yakunlangan deb belgilandi. Tahrirlash uchun yozuvni ochish (holat/xizmat/narx)?",
}

_STAFF_NEW_BOOKING_REQUEST = {
    "ru": "🆕 Новая заявка на запись\n\n👤 Клиент: {client_name}\n📱 Номер: {client_phone}\n📅 Дата и время: {datetime}\n📝 Жалоба: {purpose}",
    "uz": "🆕 Yozilish uchun yangi ariza\n\n👤 Mijoz: {client_name}\n📱 Raqam: {client_phone}\n📅 Sana va vaqt: {datetime}\n📝 Shikoyat: {purpose}",
}

_CLIENT_AUTO_CONFIRMED = {
    "ru": "✅ Ваша запись подтверждена (автоматически за 2 часа до приема).",
    "uz": "✅ Sizning yozuvingiz tasdiqlandi (qabuldan 2 soat oldin avtomatik).",
}

_PENDING_REQUEST_EXPIRED_PROPOSAL = {
    "ru": "⌛ Предложение по времени записи осталось без ответа, заявка на запись истекла.",
    "uz": "⌛ Yozuv vaqti bo'yicha taklifga javob berilmadi, ariza muddati tugadi.",
}

_PENDING_REQUEST_EXPIRED_ADMIN_INVITE = {
    "ru": "⌛ Вы не ответили на приглашение клиники на запись, заявка истекла.",
    "uz": "⌛ Siz klinikaning yozilish taklifiga javob bermadingiz, ariza muddati tugadi.",
}

_PENDING_REQUEST_EXPIRED_CLIENT_REQUEST = {
    "ru": "⌛ Ваша заявка на запись истекла без ответа клиники.",
    "uz": "⌛ Sizning yozilish arizangiz klinika javobisiz muddati tugadi.",
}

_RESCHEDULE_PROPOSED = {
    "ru": (
        "🔁 Клиника предложила другое время для вашей заявки\n\n"
        "Предложенное время: {proposed}\n\n"
        "Согласны на новое время?"
    ),
    "uz": (
        "🔁 Klinika arizangiz uchun boshqa vaqt taklif qildi\n\n"
        "Taklif qilingan vaqt: {proposed}\n\n"
        "Yangi vaqtga roziligingizmi?"
    ),
}

_APPOINTMENT_RESCHEDULE_PROPOSED = {
    "ru": (
        "🔁 Клиника предлагает перенести вашу запись на другое время\n\n"
        "Текущее время: {current}\n"
        "Предложенное время: {proposed}\n\n"
        "Согласны на новое время?"
    ),
    "uz": (
        "🔁 Klinika yozuvingizni boshqa vaqtga ko'chirishni taklif qilmoqda\n\n"
        "Hozirgi vaqt: {current}\n"
        "Taklif qilingan vaqt: {proposed}\n\n"
        "Yangi vaqtga roziligingizmi?"
    ),
}

_PROPOSAL_REMINDER = {
    "ru": (
        "⏰ Напоминаем: клиника предложила другое время для вашей заявки\n\n"
        "Предложенное время: {proposed}\n\n"
        "Пожалуйста, ответьте на предыдущее сообщение с кнопками, "
        "иначе заявка скоро автоматически аннулируется."
    ),
    "uz": (
        "⏰ Eslatma: klinika arizangiz uchun boshqa vaqt taklif qildi\n\n"
        "Taklif qilingan vaqt: {proposed}\n\n"
        "Iltimos, tugmalari bo'lgan oldingi xabarga javob bering, "
        "aks holda ariza tez orada avtomatik bekor qilinadi."
    ),
}

_APPOINTMENT_RESCHEDULE_REMINDER = {
    "ru": (
        "⏰ Напоминаем: клиника предлагает перенести вашу запись на другое время\n\n"
        "Текущее время: {current}\n"
        "Предложенное время: {proposed}\n\n"
        "Пожалуйста, ответьте на предыдущее сообщение с кнопками, "
        "иначе предложение скоро автоматически аннулируется."
    ),
    "uz": (
        "⏰ Eslatma: klinika yozuvingizni boshqa vaqtga ko'chirishni taklif qilmoqda\n\n"
        "Hozirgi vaqt: {current}\n"
        "Taklif qilingan vaqt: {proposed}\n\n"
        "Iltimos, tugmalari bo'lgan oldingi xabarga javob bering, "
        "aks holda taklif tez orada avtomatik bekor qilinadi."
    ),
}

_STALE_PROPOSAL_DEFAULT_TEXT = {
    "ru": "Это предложение больше не актуально.",
    "uz": "Bu taklif endi dolzarb emas.",
}

_STALE_DECISION_TEXT = {
    "ru": "{label} уже принял(а) решение: {outcome}.",
    "uz": "{label} allaqachon qaror qabul qildi: {outcome}.",
}

# Отдельный шаблон для случаев, когда заявка перестала быть актуальной БЕЗ решения
# сотрудника (клиент отменил запись, истёк срок ожидания). _STALE_DECISION_TEXT здесь
# не подходит: он утверждает, что кто-то «принял решение», и подставлять туда клиента
# или систему значит приписывать действие не тому актору.
_CLOSED_REQUEST_TEXT = {
    "ru": "⛔️ Заявка больше не актуальна: {outcome}.",
    "uz": "⛔️ So'rov endi dolzarb emas: {outcome}.",
}

_STAFF_PROPOSAL_ACCEPTED = {
    "ru": "✅ Клиент {client_name} согласился на предложенное время.\n\n📱 Номер: {client_phone}",
    "uz": "✅ Mijoz {client_name} taklif qilingan vaqtga rozi bo'ldi.\n\n📱 Raqam: {client_phone}",
}

_STAFF_PROPOSAL_REJECTED = {
    "ru": "❌ Клиент {client_name} отклонил предложенное время.\n\n📱 Номер: {client_phone}",
    "uz": "❌ Mijoz {client_name} taklif qilingan vaqtni rad etdi.\n\n📱 Raqam: {client_phone}",
}

_ADMIN_PROPOSAL_REMINDER = {
    "ru": "⏰ Клиент предложил другое время, ответ ещё не получен.",
    "uz": "⏰ Mijoz boshqa vaqt taklif qildi, javob hali olinmadi.",
}

_STAFF_BOOKING_CONFIRMED = {
    "ru": "✅ Заявка клиента {client_name} подтверждена ({actor}).\n\n📱 Номер: {client_phone}",
    "uz": "✅ Mijoz {client_name} arizasi tasdiqlandi ({actor}).\n\n📱 Raqam: {client_phone}",
}

_STAFF_BOOKING_REJECTED = {
    "ru": "❌ Заявка клиента {client_name} отклонена ({actor}).\n\n📱 Номер: {client_phone}",
    "uz": "❌ Mijoz {client_name} arizasi rad etildi ({actor}).\n\n📱 Raqam: {client_phone}",
}

_STAFF_RESCHEDULE_DECISION_ACCEPTED = {
    "ru": "✅ Перенос записи клиента {client_name} принят ({actor}).\n\n📱 Номер: {client_phone}",
    "uz": "✅ Mijoz {client_name} yozuvini ko'chirish so'rovi qabul qilindi ({actor}).\n\n📱 Raqam: {client_phone}",
}

_STAFF_RESCHEDULE_DECISION_REJECTED = {
    "ru": "❌ Перенос записи клиента {client_name} отклонён ({actor}).\n\n📱 Номер: {client_phone}",
    "uz": "❌ Mijoz {client_name} yozuvini ko'chirish so'rovi rad etildi ({actor}).\n\n📱 Raqam: {client_phone}",
}

_STAFF_RESCHEDULE_REQUESTED = {
    "ru": (
        "🔁 Клиент просит перенести запись\n\n"
        "👤 Клиент: {client_name}\n"
        "📱 Номер: {phone}\n"
        "📅 Текущее время: {current}\n"
        "🆕 Предложенное время: {proposed}\n"
        "📝 Услуга: {purpose}"
    ),
    "uz": (
        "🔁 Mijoz yozuvni ko'chirishni so'ramoqda\n\n"
        "👤 Mijoz: {client_name}\n"
        "📱 Raqam: {phone}\n"
        "📅 Hozirgi vaqt: {current}\n"
        "🆕 Taklif qilingan vaqt: {proposed}\n"
        "📝 Xizmat: {purpose}"
    ),
}

_CLIENT_RESCHEDULE_ACCEPTED = {
    "ru": "✅ Клиника приняла ваш перенос записи\n\nНовое время: {datetime}",
    "uz": "✅ Klinika yozuvingizni ko'chirishni qabul qildi\n\nYangi vaqt: {datetime}",
}

_CLIENT_RESCHEDULE_REJECTED = {
    "ru": (
        "❌ Клиника не смогла подтвердить перенос записи, запись отменена\n\n"
        "Если запись всё ещё нужна, свяжитесь с клиникой или отправьте новую заявку."
    ),
    "uz": (
        "❌ Klinika yozuvni ko'chirishni tasdiqlay olmadi, yozuv bekor qilindi\n\n"
        "Agar yozuv hali ham kerak bo'lsa, klinika bilan bog'laning yoki yangi ariza yuboring."
    ),
}

_CLIENT_RESCHEDULE_REQUEST_EXPIRED = {
    "ru": (
        "⌛ Предложение по времени записи истекло без ответа\n\n"
        "Ваша запись остаётся в силе на прежнее время: {datetime}\n"
        "Актуальную информацию по записи смотрите в разделе «Мои записи»."
    ),
    "uz": (
        "⌛ Yozuv vaqti bo'yicha taklif javobsiz muddati tugadi\n\n"
        "Sizning yozuvingiz avvalgi vaqtda kuchda qoladi: {datetime}\n"
        "Yozuv bo'yicha dolzarb ma'lumotni «Mening yozuvlarim» bo'limida ko'ring."
    ),
}

_APPOINTMENT_MESSAGE_HEADER = {
    "ru": "Вам назначена запись на прием",
    "uz": "Sizga qabulga yozuv belgilandi",
}

_APPOINTMENT_MESSAGE_ADMIN_INFO = {
    "ru": "👨‍⚕️ Администратор: {full_name}\n📱 Номер: {phone}\n\n",
    "uz": "👨‍⚕️ Administrator: {full_name}\n📱 Raqam: {phone}\n\n",
}

_APPOINTMENT_MESSAGE_RESCHEDULED_CTA = {
    "ru": "Клиника изменила время вашей записи. Пожалуйста, подтвердите новое время.",
    "uz": "Klinika yozuvingiz vaqtini o'zgartirdi. Iltimos, yangi vaqtni tasdiqlang.",
}

_APPOINTMENT_MESSAGE_CONFIRM_CTA = {
    "ru": "Пожалуйста, подтвердите вашу готовность посетить запись",
    "uz": "Iltimos, qabulga borishga tayyorligingizni tasdiqlang",
}

_APPOINTMENT_MESSAGE_BODY = {
    "ru": "{header}\n\n{admin_info}Дата и время: {datetime}\nУслуга: {purpose}\nКлиника: {clinic}\n\n{last_line}",
    "uz": "{header}\n\n{admin_info}Sana va vaqt: {datetime}\nXizmat: {purpose}\nKlinika: {clinic}\n\n{last_line}",
}

_NO_CLINIC_INFO = {
    "ru": "Информация не доступна",
    "uz": "Ma'lumot mavjud emas",
}

_STATUS_LINE_LABEL = {
    "ru": "Статус: {status}",
    "uz": "Holat: {status}",
}


def reminder_text(phone: str, purpose: str, datetime_value: str, lang: str = "ru") -> str:
    return _REMINDER_TEXT.get(lang, _REMINDER_TEXT["ru"]).format(
        phone=phone, purpose=escape_html(purpose), datetime=datetime_value,
    )


def appointment_cancelled_by_admin_text(
    doctor_full_name: str | None, doctor_phone: str | None, lang: str = "ru", reason: str | None = None,
) -> str:
    text = _APPOINTMENT_CANCELLED_BY_ADMIN.get(lang, _APPOINTMENT_CANCELLED_BY_ADMIN["ru"]).format(
        doctor_full_name=escape_html(doctor_full_name) if doctor_full_name else '—', doctor_phone=doctor_phone or '—',
    )
    if reason:
        reason_template = _APPOINTMENT_CANCELLED_BY_ADMIN_REASON.get(
            lang, _APPOINTMENT_CANCELLED_BY_ADMIN_REASON["ru"]
        )
        # Message is sent with HTML parse mode; reason is user-typed text, so
        # it must be escaped here (see escape_html's docstring for rationale).
        text += reason_template.format(reason=escape_html(reason))
    return text


def booking_request_rejected_text(lang: str = "ru") -> str:
    return _BOOKING_REQUEST_REJECTED.get(lang, _BOOKING_REQUEST_REJECTED["ru"])


def appointment_changed_text(datetime_value: str, purpose: str, lang: str = "ru") -> str:
    return _APPOINTMENT_CHANGED.get(lang, _APPOINTMENT_CHANGED["ru"]).format(
        datetime=datetime_value, purpose=purpose,
    )


def admin_upcoming_appointment_text(
    client_name: str, client_phone: str, datetime_value: str, purpose: str, lang: str = "ru",
) -> str:
    return _ADMIN_UPCOMING_APPOINTMENT.get(lang, _ADMIN_UPCOMING_APPOINTMENT["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone, datetime=datetime_value,
        purpose=escape_html(purpose),
    )


def admin_cancellation_text(
    client_name: str, client_phone: str | None, datetime_value: str, purpose: str, lang: str = "ru",
) -> str:
    return _ADMIN_CANCELLATION.get(lang, _ADMIN_CANCELLATION["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', datetime=datetime_value,
        purpose=escape_html(purpose),
    )


def staff_appointment_cancelled_text(
    client_name: str,
    client_phone: str | None,
    actor: str,
    datetime_value: str,
    purpose: str,
    lang: str = "ru",
    deleted: bool = False,
) -> str:
    template = _STAFF_APPOINTMENT_DELETED if deleted else _STAFF_APPOINTMENT_CANCELLED
    return template.get(lang, template["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
        datetime=datetime_value, purpose=escape_html(purpose),
    )


def staff_appointment_created_text(
    client_name: str,
    client_phone: str | None,
    actor: str,
    datetime_value: str,
    purpose: str,
    lang: str = "ru",
    doctor_full_name: str | None = None,
) -> str:
    return _STAFF_APPOINTMENT_CREATED.get(lang, _STAFF_APPOINTMENT_CREATED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
        doctor_full_name=escape_html(doctor_full_name) if doctor_full_name else '—',
        datetime=datetime_value, purpose=escape_html(purpose),
    )


def admin_client_changed_time_text(
    client_name: str, client_phone: str | None, datetime_value: str, lang: str = "ru",
) -> str:
    return _ADMIN_CLIENT_CHANGED_TIME.get(lang, _ADMIN_CLIENT_CHANGED_TIME["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', datetime=datetime_value,
    )


def admin_confirmation_text(
    client_name: str, client_phone: str | None, datetime_value: str, purpose: str, lang: str = "ru",
) -> str:
    return _ADMIN_CONFIRMATION.get(lang, _ADMIN_CONFIRMATION["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', datetime=datetime_value,
        purpose=escape_html(purpose),
    )


def admin_completion_prompt(appointment_id: int, lang: str = "ru") -> str:
    return _ADMIN_COMPLETION_PROMPT.get(lang, _ADMIN_COMPLETION_PROMPT["ru"]).format(
        appointment_id=appointment_id,
    )


def staff_new_booking_request_text(
    client_name: str, client_phone: str | None, datetime_value: str, purpose: str, lang: str = "ru",
) -> str:
    return _STAFF_NEW_BOOKING_REQUEST.get(lang, _STAFF_NEW_BOOKING_REQUEST["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', datetime=datetime_value,
        purpose=escape_html(purpose),
    )


def client_auto_confirmed_text(lang: str = "ru") -> str:
    return _CLIENT_AUTO_CONFIRMED.get(lang, _CLIENT_AUTO_CONFIRMED["ru"])


def pending_request_expired_proposal_text(lang: str = "ru") -> str:
    return _PENDING_REQUEST_EXPIRED_PROPOSAL.get(lang, _PENDING_REQUEST_EXPIRED_PROPOSAL["ru"])


def pending_request_expired_admin_invite_text(lang: str = "ru") -> str:
    return _PENDING_REQUEST_EXPIRED_ADMIN_INVITE.get(lang, _PENDING_REQUEST_EXPIRED_ADMIN_INVITE["ru"])


def pending_request_expired_client_request_text(lang: str = "ru") -> str:
    return _PENDING_REQUEST_EXPIRED_CLIENT_REQUEST.get(lang, _PENDING_REQUEST_EXPIRED_CLIENT_REQUEST["ru"])


def reschedule_proposed_text(proposed: str, lang: str = "ru") -> str:
    return _RESCHEDULE_PROPOSED.get(lang, _RESCHEDULE_PROPOSED["ru"]).format(proposed=proposed)


def appointment_reschedule_proposed_text(current: str, proposed: str, lang: str = "ru") -> str:
    return _APPOINTMENT_RESCHEDULE_PROPOSED.get(lang, _APPOINTMENT_RESCHEDULE_PROPOSED["ru"]).format(
        current=current, proposed=proposed,
    )


def proposal_reminder_text(proposed: str, lang: str = "ru") -> str:
    return _PROPOSAL_REMINDER.get(lang, _PROPOSAL_REMINDER["ru"]).format(proposed=proposed)


def appointment_reschedule_reminder_text(current: str, proposed: str, lang: str = "ru") -> str:
    return _APPOINTMENT_RESCHEDULE_REMINDER.get(lang, _APPOINTMENT_RESCHEDULE_REMINDER["ru"]).format(
        current=current, proposed=proposed,
    )


def stale_proposal_default_text(lang: str = "ru") -> str:
    return _STALE_PROPOSAL_DEFAULT_TEXT.get(lang, _STALE_PROPOSAL_DEFAULT_TEXT["ru"])


def stale_decision_text(
    decided_by_label: str, outcome_text: str, lang: str = "ru", appointment_summary: str | None = None,
) -> str:
    text = _STALE_DECISION_TEXT.get(lang, _STALE_DECISION_TEXT["ru"]).format(
        label=decided_by_label, outcome=outcome_text,
    )
    if appointment_summary:
        text = f"{text}\n\n{appointment_summary}"

    return text


def closed_request_text(outcome_text: str, lang: str = "ru") -> str:
    return _CLOSED_REQUEST_TEXT.get(lang, _CLOSED_REQUEST_TEXT["ru"]).format(outcome=outcome_text)


def staff_proposal_accepted_text(client_name: str, client_phone: str | None, lang: str = "ru") -> str:
    return _STAFF_PROPOSAL_ACCEPTED.get(lang, _STAFF_PROPOSAL_ACCEPTED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—',
    )


def staff_proposal_rejected_text(client_name: str, client_phone: str | None, lang: str = "ru") -> str:
    return _STAFF_PROPOSAL_REJECTED.get(lang, _STAFF_PROPOSAL_REJECTED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—',
    )


def admin_proposal_reminder_text(lang: str = "ru") -> str:
    return _ADMIN_PROPOSAL_REMINDER.get(lang, _ADMIN_PROPOSAL_REMINDER["ru"])


def staff_booking_confirmed_text(client_name: str, client_phone: str | None, actor: str, lang: str = "ru") -> str:
    return _STAFF_BOOKING_CONFIRMED.get(lang, _STAFF_BOOKING_CONFIRMED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
    )


def staff_booking_rejected_text(client_name: str, client_phone: str | None, actor: str, lang: str = "ru") -> str:
    return _STAFF_BOOKING_REJECTED.get(lang, _STAFF_BOOKING_REJECTED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
    )


def staff_reschedule_decision_accepted_text(
    client_name: str, client_phone: str | None, actor: str, lang: str = "ru",
) -> str:
    return _STAFF_RESCHEDULE_DECISION_ACCEPTED.get(lang, _STAFF_RESCHEDULE_DECISION_ACCEPTED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
    )


def staff_reschedule_decision_rejected_text(
    client_name: str, client_phone: str | None, actor: str, lang: str = "ru",
) -> str:
    return _STAFF_RESCHEDULE_DECISION_REJECTED.get(lang, _STAFF_RESCHEDULE_DECISION_REJECTED["ru"]).format(
        client_name=escape_html(client_name), client_phone=client_phone or '—', actor=actor,
    )


def staff_reschedule_requested_text(
    client_name: str, phone: str, current: str, proposed: str, purpose: str, lang: str = "ru",
) -> str:
    return _STAFF_RESCHEDULE_REQUESTED.get(lang, _STAFF_RESCHEDULE_REQUESTED["ru"]).format(
        client_name=escape_html(client_name), phone=phone, current=current, proposed=proposed,
        purpose=escape_html(purpose),
    )


def client_reschedule_accepted_text(datetime_value: str, lang: str = "ru") -> str:
    return _CLIENT_RESCHEDULE_ACCEPTED.get(lang, _CLIENT_RESCHEDULE_ACCEPTED["ru"]).format(datetime=datetime_value)


def client_reschedule_rejected_text(lang: str = "ru") -> str:
    return _CLIENT_RESCHEDULE_REJECTED.get(lang, _CLIENT_RESCHEDULE_REJECTED["ru"])


def client_reschedule_request_expired_text(datetime_value: str, lang: str = "ru") -> str:
    return _CLIENT_RESCHEDULE_REQUEST_EXPIRED.get(lang, _CLIENT_RESCHEDULE_REQUEST_EXPIRED["ru"]).format(
        datetime=datetime_value,
    )


def _format_datetime_value(value: str, lang: str = "ru") -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value), lang)
    except ValueError:
        return value


class AppointmentNotificationService:
    def __init__(
        self,
        notifier: TelegramNotifier,
        user_repo: UserRepository,
        appointment_repo: AppointmentRepository
    ):
        self.notifier = notifier
        self.user_repo = user_repo
        self.appointment_repo = appointment_repo

    async def _resolve_lang(self, telegram_id: int) -> str:
        user = await self.user_repo.get_user_by_telegram_id(telegram_id)
        return user.language if user is not None else "ru"

    async def notify_client_appointment_with_buttons(
        self, appointment: Appointment, use_invite_kb: bool = True, rescheduled: bool = False
    ) -> int | None:
        """Send full appointment notification to client WITH confirmation buttons (on creation).

        use_invite_kb controls which keyboard is attached:
        - True (default): the record is still an unresolved admin-created invite
          (PENDING+ADMIN) — the client sees Confirm / Propose different time / Cancel.
        - False: the record is already CONFIRMED (e.g. the clinic just approved the
          client's own self-booking request) — no decision is pending, so no
          negotiation buttons are shown.

        rescheduled=True adjusts the status line for a PENDING appointment to make
        clear the clinic just changed the time of an existing appointment, rather
        than reading like a brand-new invite.

        Returns the sent message's message_id (to be persisted so later reminders can reply
        to it), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        admin = await self.user_repo.get_user_by_id(appointment.doctor_id) if appointment.doctor_id else None
        message_text = self._build_appointment_message(
            appointment, admin, rescheduled=rescheduled, lang=client.language,
        )

        reply_markup = (
            appointment_invite_kb(appointment.id) if use_invite_kb
            else appointment_reminder_details_kb(appointment.id)
        )

        return await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reply_markup,
        )

    async def notify_client_reminder_without_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITHOUT buttons (24h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=reminder_text(
                client.phone or '—',
                appointment.purpose,
                _format_datetime_value(appointment.datetime, client.language),
                client.language,
            ),
            reply_markup=appointment_reminder_details_kb(appointment.id),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_reminder_with_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITH confirmation buttons (2h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=reminder_text(
                client.phone or '—',
                appointment.purpose,
                _format_datetime_value(appointment.datetime, client.language),
                client.language,
            ),
            reply_markup=appointment_reminder_with_buttons_kb(appointment.id),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_appointment_details(self, appointment: Appointment) -> bool:
        """Rebuild the original confirmation message into a full appointment details card.

        Edits the original notification_message_id in place; falls back to sending a
        new message if that original message is gone/inaccessible.

        Returns True if the card was shown (edited or newly sent), False if the
        client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        admin = await self.user_repo.get_user_by_id(appointment.doctor_id) if appointment.doctor_id else None
        message_text = self._build_appointment_message(appointment, admin, lang=client.language)

        if appointment.status == AppointmentStatus.PENDING:
            reply_markup = appointment_invite_kb(appointment.id)
        else:
            reply_markup = appointment_reminder_details_kb(appointment.id)

        if appointment.notification_message_id is not None and await self.notifier.try_edit_message_text(
            chat_id=client.telegram_user_id,
            message_id=appointment.notification_message_id,
            text=message_text,
            reply_markup=reply_markup,
        ):
            return True

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reply_markup,
        )
        return True

    async def notify_client_appointment_cancelled_by_admin(
        self, appointment: Appointment, reason: str | None = None
    ) -> bool:
        """Notify client that their appointment was cancelled by an administrator.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=appointment_cancelled_by_admin_text(
                appointment.doctor_full_name, appointment.doctor_phone, client.language, reason,
            ),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_booking_request_rejected(self, appointment: Appointment) -> bool:
        """Notify client that their self-booking request was declined by the clinic.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=booking_request_rejected_text(client.language),
        )

        return True

    # DISABLED INTENTIONALLY (2026-08-04, by explicit user request) — do NOT restore.
    # A prior session (commit 1b1322c) treated this as a bug and re-enabled it; that was wrong.
    # The call site (appointment_browser.py's notify_appointment_changed) already no-ops safely
    # via AttributeError caught by its own try/except, so no other change is needed to keep it off.
    # async def notify_client_appointment_changed(self, appointment: Appointment) -> bool:
    #     """Notify client that details of their appointment (datetime or purpose) were changed.
    #
    #     Returns True if message sent, False if user not found or no telegram_id.
    #     """
    #     client = await self.user_repo.get_client_by_id(appointment.client_id)
    #
    #     if client is None or client.telegram_user_id is None:
    #         return False
    #
    #     await self.notifier.send_message(
    #         chat_id=client.telegram_user_id,
    #         text=appointment_changed_text(appointment.datetime, appointment.purpose, client.language),
    #         reply_to_message_id=self._reply_to_message_id(appointment),
    #     )
    #
    #     return True

    def _reply_to_message_id(self, appointment: Appointment) -> int | None:
        return appointment.notification_message_id

    async def _admin_reply_to_message_id(self, appointment: Appointment, chat_id: int) -> int | None:
        """Resolve the reply-to anchor for an admin/staff-facing notification.

        Looks up the most recently recorded notification message for this
        appointment in this specific chat (regardless of kind), since admin and
        doctor are in different Telegram chats and a single stored
        admin_notification_message_id column cannot be a correct anchor for both.
        """
        return await self.appointment_repo.get_latest_notification_message_id(appointment.id, chat_id)

    async def notify_admin_upcoming_appointment(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Send reminder to admin about upcoming appointment WITHOUT buttons.

        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)
        client_phone = client.phone if client else "—"
        lang = await self._resolve_lang(admin_telegram_id)

        message_text = admin_upcoming_appointment_text(
            client_name, client_phone, appointment.datetime, appointment.purpose, lang,
        )

        try:
            return await self.notifier.send_message(
                chat_id=admin_telegram_id,
                text=message_text,
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить напоминание администратору {admin_telegram_id}: {e}"
            ) from e

    async def notify_admin_cancellation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> int | None:
        """Send cancellation notification to admin.

        Returns the sent message's message_id.
        """
        lang = await self._resolve_lang(admin_telegram_id)
        return await self.notifier.send_message(
            chat_id=admin_telegram_id,
            text=admin_cancellation_text(
                client_name, appointment.client_phone,
                _format_datetime_value(appointment.datetime, lang), appointment.purpose, lang,
            ),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, admin_telegram_id),
        )

    async def notify_admin_client_changed_time(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify admin that the client changed the time of their own pending self-booking request."""
        lang = await self._resolve_lang(admin_telegram_id)
        await self.notifier.send_message(
            chat_id=admin_telegram_id,
            text=admin_client_changed_time_text(
                client_name, appointment.client_phone, _format_datetime_value(appointment.datetime, lang), lang,
            ),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, admin_telegram_id),
        )

    async def notify_admin_confirmation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> int | None:
        """Send confirmation notification to admin.

        Returns the sent message's message_id.
        """
        lang = await self._resolve_lang(admin_telegram_id)
        return await self.notifier.send_message(
            chat_id=admin_telegram_id,
            text=admin_confirmation_text(
                client_name, appointment.client_phone,
                _format_datetime_value(appointment.datetime, lang), appointment.purpose, lang,
            ),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, admin_telegram_id),
        )

    async def notify_admin_completion(self, admin_telegram_id: int, appointment: Appointment) -> int | None:
        """Ask admin whether to make post-appointment corrections before finalizing the status.

        Returns the sent message's message_id on success.
        """
        lang = await self._resolve_lang(admin_telegram_id)
        return await self.notifier.send_message(
            chat_id=admin_telegram_id,
            text=admin_completion_prompt(appointment.id, lang),
            reply_markup=completion_followup_kb(appointment.id),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, admin_telegram_id),
        )

    async def notify_staff_new_booking_request(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Notify the chosen staff member about a new client self-booking request.

        Sends Confirm / Propose-different-time / Reject action buttons.
        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        lang = await self._resolve_lang(staff_telegram_id)
        message_text = staff_new_booking_request_text(
            client_name, appointment.client_phone, appointment.datetime, appointment.purpose, lang,
        )

        try:
            message_id = await self.notifier.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=booking_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

        return message_id

    async def notify_client_auto_confirmed(self, appointment: Appointment) -> bool:
        """[LEGACY] Notify client that their appointment was auto-confirmed.

        Previously called 2 hours before the appointment when the admin did not
        manually confirm a PENDING appointment. This notification is now only sent
        for legacy jobs persisted in the job store before the auto-confirm mechanism
        was retired. New appointments no longer use auto-confirm.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=client_auto_confirmed_text(client.language),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_pending_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that their unanswered PENDING request has expired.

        Covers three cases: a client self-booking request the clinic never answered;
        an admin-created invite the client never answered at all; and an admin-created
        appointment where the client proposed their own time and the clinic never
        answered that counter-proposal. When a proposal was outstanding, the wording
        stays neutral about which side missed the deadline.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        if appointment.proposed_datetime is not None:
            text = pending_request_expired_proposal_text(client.language)
        elif appointment.created_by == CreatedBy.ADMIN:
            text = pending_request_expired_admin_invite_text(client.language)
        else:
            text = pending_request_expired_client_request_text(client.language)

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=text,
        )

        return True

    async def notify_client_reschedule_proposed(self, appointment: Appointment) -> int | None:
        """Notify client that the clinic proposed a different time for their request.

        Returns the sent message's message_id (to be persisted so the proposal message
        can later be closed), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        message_text = reschedule_proposed_text(
            _format_datetime_value(appointment.proposed_datetime, client.language), client.language,
        )

        return await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reschedule_proposal_kb(appointment.id),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

    async def notify_client_appointment_reschedule_proposed(self, appointment: Appointment) -> int | None:
        """Notify client that the clinic proposed a different time for their confirmed appointment.

        Returns the sent message's message_id (to be persisted so the proposal message
        can later be closed), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        message_text = appointment_reschedule_proposed_text(
            _format_datetime_value(appointment.datetime, client.language),
            _format_datetime_value(appointment.proposed_datetime, client.language),
            client.language,
        )

        return await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reschedule_proposal_kb(appointment.id),
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

    async def notify_client_proposal_reminder(self, appointment: Appointment) -> bool:
        """Remind client that the clinic's proposed time is still awaiting a response.

        Sent partway through the proposal window, as a plain reply to the original
        proposal message (no buttons of its own — the client answers there).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = proposal_reminder_text(
            _format_datetime_value(appointment.proposed_datetime, client.language), client.language,
        )

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_to_message_id=appointment.proposal_message_id,
        )

        return True

    async def notify_client_appointment_reschedule_reminder(self, appointment: Appointment) -> bool:
        """Remind client that the clinic's proposed reschedule for their confirmed
        appointment is still awaiting a response.

        Sent partway through the reschedule window, as a plain reply to the original
        proposal message (no buttons of its own — the client answers there).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = appointment_reschedule_reminder_text(
            _format_datetime_value(appointment.datetime, client.language),
            _format_datetime_value(appointment.proposed_datetime, client.language),
            client.language,
        )

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_to_message_id=appointment.proposal_message_id,
        )

        return True

    async def close_reschedule_proposal_message(
        self, chat_id: int, message_id: int, text: str | None = None
    ) -> None:
        """Edit a stale reschedule-proposal message so it no longer looks actionable."""
        if text is None:
            text = stale_proposal_default_text(await self._resolve_lang(chat_id))

        await self.notifier.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)

    async def invalidate_stale_decision_message(
        self,
        chat_id: int,
        message_id: int,
        decided_by_label: dict[str, str],
        outcome_text: dict[str, str],
        appointment_summary: str | None = None,
    ) -> None:
        """Edit a stale staff notification once another recipient has already decided.

        decided_by_label/outcome_text are resolved to this recipient's own language
        (independent of the acting user's language), since siblings receiving this
        invalidation may use a different language than the staff member who decided.

        appointment_summary, if provided, is an already-formatted (Handler-layer)
        appointment card appended below the decision text. It has no length limit
        (unlike the 200-character show_alert popup), so it's the place to surface
        client/phone/time/status details to the staff member who lost the race.

        Strips the inline keyboard and replaces the text so the message no longer
        looks actionable. Never raises — a failed edit (message deleted, bot blocked,
        "message is not modified") is logged and swallowed so it doesn't abort a loop
        of invalidation calls across multiple recipients.
        """
        lang = await self._resolve_lang(chat_id)
        label = decided_by_label.get(lang, decided_by_label.get("ru", ""))
        outcome = outcome_text.get(lang, outcome_text.get("ru", ""))
        if not await self.notifier.try_edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=stale_decision_text(label, outcome, lang, appointment_summary),
            reply_markup=None,
        ):
            logger.warning(
                f"Failed to invalidate stale decision message {message_id} in chat {chat_id}"
            )

    async def invalidate_closed_request_message(
        self,
        chat_id: int,
        message_id: int,
        outcome_text: dict[str, str],
    ) -> None:
        """Edit a staff notification whose request closed without any staff decision.

        Used when the client cancelled the appointment or the request expired
        unanswered: the inline keyboard is still live in every staff chat, but
        pressing it can only ever produce an error popup. Unlike
        invalidate_stale_decision_message there is no acting staff member to name,
        so the text carries only the outcome.

        outcome_text is resolved to this recipient's own language.

        Never raises — a failed edit (message deleted, bot blocked) is logged and
        swallowed so it doesn't abort a loop over several recipients.
        """
        lang = await self._resolve_lang(chat_id)
        outcome = outcome_text.get(lang, outcome_text.get("ru", ""))
        if not await self.notifier.try_edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=closed_request_text(outcome, lang),
            reply_markup=None,
        ):
            logger.warning(
                f"Failed to invalidate closed request message {message_id} in chat {chat_id}"
            )

    async def notify_staff_proposal_accepted(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client accepted the proposed new time."""
        lang = await self._resolve_lang(staff_telegram_id)
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_proposal_accepted_text(client_name, appointment.client_phone, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_proposal_rejected(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client rejected the proposed new time."""
        lang = await self._resolve_lang(staff_telegram_id)
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_proposal_rejected_text(client_name, appointment.client_phone, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_booking_confirmed(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str,
    ) -> None:
        """Notify other staff that a colleague confirmed a client's booking request."""
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_booking_confirmed_text(client_name, appointment.client_phone, actor, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_booking_rejected(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str,
    ) -> None:
        """Notify other staff that a colleague rejected a client's booking request."""
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_booking_rejected_text(client_name, appointment.client_phone, actor, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_reschedule_decision_accepted(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str,
    ) -> None:
        """Notify other staff that a colleague accepted a client's reschedule request."""
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_reschedule_decision_accepted_text(client_name, appointment.client_phone, actor, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_reschedule_decision_rejected(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str,
    ) -> None:
        """Notify other staff that a colleague rejected a client's reschedule request."""
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_reschedule_decision_rejected_text(client_name, appointment.client_phone, actor, lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, staff_telegram_id),
        )

    async def notify_staff_appointment_cancelled(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str | None,
        deleted: bool = False,
    ) -> int | None:
        """Notify other staff that a colleague cancelled or deleted this appointment.

        client_name is the client's full name, or None if the client record could
        not be resolved -- in that case a localized "Client"/"Mijoz" fallback is
        used, resolved to this recipient's own language (independent of the
        acting user's language).

        Returns the sent message's message_id.
        """
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        display_name = client_name or DEFAULT_UNKNOWN_CLIENT_LABEL.get(lang, DEFAULT_UNKNOWN_CLIENT_LABEL["ru"])
        reply_to_message_id = (
            None if deleted else await self._admin_reply_to_message_id(appointment, staff_telegram_id)
        )
        return await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_appointment_cancelled_text(
                display_name, appointment.client_phone, actor,
                _format_datetime_value(appointment.datetime, lang), appointment.purpose, lang,
                deleted=deleted,
            ),
            reply_to_message_id=reply_to_message_id,
        )

    async def notify_staff_appointment_created(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        actor_label: dict[str, str],
        client_name: str | None,
    ) -> int | None:
        """Notify other staff that a colleague created this appointment.

        client_name is the client's full name, or None if the client record could
        not be resolved -- resolved the same way as notify_staff_appointment_cancelled.

        Returns the sent message's message_id.
        """
        lang = await self._resolve_lang(staff_telegram_id)
        actor = actor_label.get(lang, actor_label.get("ru", ""))
        display_name = client_name or DEFAULT_UNKNOWN_CLIENT_LABEL.get(lang, DEFAULT_UNKNOWN_CLIENT_LABEL["ru"])
        return await self.notifier.send_message(
            chat_id=staff_telegram_id,
            text=staff_appointment_created_text(
                display_name, appointment.client_phone, actor,
                _format_datetime_value(appointment.datetime, lang), appointment.purpose, lang,
                doctor_full_name=appointment.doctor_full_name,
            ),
        )

    async def notify_admin_proposal_reminder(self, telegram_id: int, appointment: Appointment) -> None:
        """Remind the clinic that the client's proposed time is still awaiting a response.

        Status-neutral: reused for both an outstanding client counter-proposal on a
        PENDING admin-created invite, and a client-requested reschedule on a CONFIRMED
        appointment. Sent as a reply to the original admin notification message.
        """
        lang = await self._resolve_lang(telegram_id)
        await self.notifier.send_message(
            chat_id=telegram_id,
            text=admin_proposal_reminder_text(lang),
            reply_to_message_id=await self._admin_reply_to_message_id(appointment, telegram_id),
        )

    async def notify_staff_reschedule_requested(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Notify staff that a client wants to reschedule a confirmed appointment.

        Sends Accept / Reject action buttons.
        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        lang = await self._resolve_lang(staff_telegram_id)
        message_text = staff_reschedule_requested_text(
            client_name,
            appointment.client_phone or '—',
            _format_datetime_value(appointment.datetime, lang),
            _format_datetime_value(appointment.proposed_datetime, lang),
            appointment.purpose,
            lang,
        )

        try:
            message_id = await self.notifier.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=reschedule_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

        return message_id

    async def notify_client_reschedule_accepted(self, appointment: Appointment) -> bool:
        """Notify client that the clinic accepted their reschedule request.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = client_reschedule_accepted_text(
            _format_datetime_value(appointment.datetime, client.language), client.language,
        )

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_reschedule_rejected(self, appointment: Appointment) -> bool:
        """Notify client that the clinic could not accommodate their reschedule request.

        The appointment is cancelled as a result — this is a terminal outcome,
        not a return to the original confirmed time.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = client_reschedule_rejected_text(client.language)

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    async def notify_client_reschedule_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that a reschedule proposal on their appointment went unanswered in time.

        Used both when the client proposed a time and the clinic never answered, and
        when the clinic proposed a time and the client never answered — the wording
        stays neutral about which side missed the deadline. The original appointment
        remains CONFIRMED and unchanged.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = client_reschedule_request_expired_text(
            _format_datetime_value(appointment.datetime, client.language), client.language,
        )

        await self.notifier.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_to_message_id=self._reply_to_message_id(appointment),
        )

        return True

    def _build_appointment_message(
        self,
        appointment: Appointment,
        admin: User | None = None,
        rescheduled: bool = False,
        lang: str = "ru",
    ) -> str:
        """Build appointment notification message for client."""
        admin_info = ""
        if admin:
            admin_info = _APPOINTMENT_MESSAGE_ADMIN_INFO.get(lang, _APPOINTMENT_MESSAGE_ADMIN_INFO["ru"]).format(
                full_name=escape_html(admin.full_name or ''), phone=admin.phone or '—',
            )

        if appointment.status == AppointmentStatus.PENDING:
            last_line = (
                _APPOINTMENT_MESSAGE_RESCHEDULED_CTA.get(lang, _APPOINTMENT_MESSAGE_RESCHEDULED_CTA["ru"])
                if rescheduled
                else _APPOINTMENT_MESSAGE_CONFIRM_CTA.get(lang, _APPOINTMENT_MESSAGE_CONFIRM_CTA["ru"])
            )
        else:
            status_text = status_label(appointment.status, lang)
            last_line = _STATUS_LINE_LABEL.get(lang, _STATUS_LINE_LABEL["ru"]).format(status=status_text)

        message = _APPOINTMENT_MESSAGE_BODY.get(lang, _APPOINTMENT_MESSAGE_BODY["ru"]).format(
            header=_APPOINTMENT_MESSAGE_HEADER.get(lang, _APPOINTMENT_MESSAGE_HEADER["ru"]),
            admin_info=admin_info,
            datetime=appointment.datetime,
            purpose=escape_html(appointment.purpose),
            clinic=appointment.clinic_name or _NO_CLINIC_INFO.get(lang, _NO_CLINIC_INFO["ru"]),
            last_line=last_line,
        )

        if appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is not None:
            proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT, lang=lang)
            message += f"\n\n{proposal_line}\n{reschedule_negotiation_note(lang)}"

        return message
