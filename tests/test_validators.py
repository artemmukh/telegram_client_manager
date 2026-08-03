import pytest

from bot.exceptions.user_exceptions import (
    InvalidBirthDateError,
    InvalidFullNameError,
    InvalidPhoneError,
    ReplyMenuButtonInputError,
    ValidationError,
)
from bot.validators.validators import (
    FULL_NAME_PATTERN,
    validate_birth_date,
    validate_datetime,
    validate_fields_filled,
    validate_full_name,
    validate_phone,
    validate_price,
    validate_purpose,
)


@pytest.mark.parametrize(
    "full_name",
    [
        "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d \u0418\u0432\u0430\u043d\u043e\u0432\u0438\u0447",
        "\u041f\u0435\u0442\u0440\u043e\u0432-\u0412\u043e\u0434\u043a\u0438\u043d \u041a\u0443\u0437\u044c\u043c\u0430",
    ],
)
def test_validate_full_name_accepts_valid_cyrillic_names(full_name):
    assert validate_full_name(full_name, FULL_NAME_PATTERN) == full_name


@pytest.mark.parametrize(
    "full_name",
    [
        "",
        "\u0438\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        "\u0418\u0432\u0430\u043d",
        "Ivanov Ivan",
        "\u0418\u0432\u0430\u043d\u043e\u0432  \u0418\u0432\u0430\u043d",
        "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d 123",
    ],
)
def test_validate_full_name_rejects_invalid_names(full_name):
    with pytest.raises(InvalidFullNameError):
        validate_full_name(full_name, FULL_NAME_PATTERN)


def test_validate_full_name_accepts_name_at_the_fifty_char_limit():
    full_name = "И" + "в" * 23 + " " + "В" + "в" * 24
    assert len(full_name) == 50
    assert validate_full_name(full_name, FULL_NAME_PATTERN) == full_name


def test_validate_full_name_rejects_name_over_fifty_chars():
    full_name = "И" + "в" * 23 + " " + "В" + "в" * 25
    assert len(full_name) == 51
    with pytest.raises(InvalidFullNameError):
        validate_full_name(full_name, FULL_NAME_PATTERN)


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("901234567", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("+998901234567", "+998901234567"),
        ("(90) 123-45-67", "+998901234567"),
    ],
)
def test_validate_phone_accepts_and_normalizes_valid_numbers(raw_phone, expected):
    assert validate_phone(raw_phone) == expected


@pytest.mark.parametrize(
    "raw_phone",
    ["", "12345", "+997901234567", "+99890123456a", "+9989012345678"],
)
def test_validate_phone_rejects_invalid_numbers(raw_phone):
    with pytest.raises(InvalidPhoneError):
        validate_phone(raw_phone)


def test_validate_fields_filled_accepts_required_registration_data():
    assert validate_fields_filled({"full_name": "Name", "phone": "+998901234567"}) is None


@pytest.mark.parametrize("data", [{"phone": "+998901234567"}, {"full_name": "Name"}])
def test_validate_fields_filled_rejects_missing_required_fields(data):
    with pytest.raises(ValidationError):
        validate_fields_filled(data)


def test_validate_birth_date_accepts_valid_date_and_normalizes_to_iso():
    assert validate_birth_date("05.03.1990") == "1990-03-05"


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        "1990-03-05",
        "5.3.1990",
        "05/03/1990",
        "05.03.90",
        "not a date",
    ],
)
def test_validate_birth_date_rejects_malformed_format(raw_value):
    with pytest.raises(InvalidBirthDateError):
        validate_birth_date(raw_value)


def test_validate_birth_date_rejects_impossible_calendar_date():
    with pytest.raises(InvalidBirthDateError):
        validate_birth_date("31.02.1990")


def test_validate_birth_date_raises_exact_exception_type():
    with pytest.raises(InvalidBirthDateError) as exc_info:
        validate_birth_date("not a date")

    assert type(exc_info.value) is InvalidBirthDateError


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт", "📍 Локация", "👤 Управление клиентами"],
)
def test_validate_full_name_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_full_name(button_label, FULL_NAME_PATTERN)


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт"],
)
def test_validate_phone_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_phone(button_label)


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт"],
)
def test_validate_birth_date_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_birth_date(button_label)


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт"],
)
def test_validate_purpose_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_purpose(button_label)


def test_validate_purpose_accepts_ordinary_text():
    assert validate_purpose("Консультация") == "Консультация"


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт"],
)
def test_validate_price_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_price(button_label)


def test_validate_price_accepts_ordinary_value():
    assert validate_price("150000") == 150000.0


@pytest.mark.parametrize(
    "button_label",
    ["📋 Прайс-лист", "⚙️ Мой профиль", "📱 Отправить контакт"],
)
def test_validate_datetime_rejects_reply_menu_button_labels(button_label):
    with pytest.raises(ReplyMenuButtonInputError):
        validate_datetime(button_label)


def test_validate_datetime_accepts_ordinary_value():
    assert validate_datetime("2026-07-10 14:30") == "2026-07-10 14:30"


def test_purpose_matching_button_word_without_emoji_does_not_collide():
    """A legitimately typed purpose that happens to share a word with a
    button label (but without the button's emoji prefix) must NOT be
    rejected -- is_reply_menu_label is an exact match, not a substring
    match."""
    assert validate_purpose("Локация") == "Локация"
