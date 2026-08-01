import pytest

import bot.messages.common as msg

REPRESENTATIVE_ACCESSORS = [
    msg.registration_intro,
    msg.send_contact_prompt,
    msg.already_registered,
    msg.phone_already_linked,
    msg.contact_ownership_mismatch,
    msg.full_name_prompt,
    msg.birth_date_prompt,
    msg.gender_prompt,
    msg.registration_success,
    msg.registration_guide,
]


@pytest.mark.parametrize("accessor", REPRESENTATIVE_ACCESSORS)
def test_uz_accessor_returns_non_empty_text_distinct_from_ru(accessor):
    ru_text = accessor("ru")
    uz_text = accessor("uz")

    assert ru_text
    assert uz_text
    assert uz_text != ru_text


def test_unknown_lang_falls_back_to_ru():
    assert msg.registration_intro("fr") == msg.registration_intro("ru")


def test_greetings_differ_by_language():
    ru_greeting = msg.admin_greeting("Иван", "ru")
    uz_greeting = msg.admin_greeting("Иван", "uz")
    assert ru_greeting != uz_greeting
    assert ru_greeting and uz_greeting

    ru_client_greeting = msg.client_greeting("Иван", "Клиника", "ru")
    uz_client_greeting = msg.client_greeting("Иван", "Клиника", "uz")
    assert ru_client_greeting != uz_client_greeting
    assert ru_client_greeting and uz_client_greeting
