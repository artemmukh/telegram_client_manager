from datetime import date

from bot.handlers.utils.client_utils.booking_helpers import build_booking_confirmation_text


def test_build_booking_confirmation_text_contains_key_fields():
    text = build_booking_confirmation_text(
        doctor_name="Иванов Иван",
        day=date(2026, 7, 10),
        slot="14:30",
        complaint="Болит зуб",
        clinic_name="Зуб Мудрости",
    )

    assert "Иванов Иван" in text
    assert "Болит зуб" in text
    assert "Зуб Мудрости" in text


def test_build_booking_confirmation_text_handles_missing_clinic_name():
    text = build_booking_confirmation_text(
        doctor_name="Иванов Иван",
        day=date(2026, 7, 10),
        slot="14:30",
        complaint="Болит зуб",
        clinic_name=None,
    )

    assert "Информация не доступна" in text
