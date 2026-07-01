import pytest

from bot.exceptions.user_exceptions import (
    InvalidFullNameError,
    InvalidPhoneError,
    PhoneAlreadyExistsError,
    ValidationError,
)
from bot.validators.validators import (
    validate_fields_filled,
    validate_full_name,
    validate_phone,
    validate_phone_available,
)


class PhoneLookupRepository:
    def __init__(self, existing_phones):
        self.existing_phones = set(existing_phones)

    async def phone_exists(self, phone: str) -> bool:
        return phone in self.existing_phones


@pytest.mark.parametrize(
    "full_name",
    [
        "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d \u0418\u0432\u0430\u043d\u043e\u0432\u0438\u0447",
        "\u041f\u0435\u0442\u0440\u043e\u0432-\u0412\u043e\u0434\u043a\u0438\u043d \u041a\u0443\u0437\u044c\u043c\u0430",
    ],
)
def test_validate_full_name_accepts_valid_cyrillic_names(full_name):
    assert validate_full_name(full_name) is None


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
        validate_full_name(full_name)


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


@pytest.mark.asyncio
async def test_validate_phone_available_allows_missing_phone():
    repo = PhoneLookupRepository(existing_phones=set())

    assert await validate_phone_available(repo, "+998901234567") is None


@pytest.mark.asyncio
async def test_validate_phone_available_rejects_existing_phone():
    repo = PhoneLookupRepository(existing_phones={"+998901234567"})

    with pytest.raises(PhoneAlreadyExistsError):
        await validate_phone_available(repo, "+998901234567")


def test_validate_fields_filled_accepts_required_registration_data():
    assert validate_fields_filled({"full_name": "Name", "phone": "+998901234567"}) is None


@pytest.mark.parametrize("data", [{"phone": "+998901234567"}, {"full_name": "Name"}])
def test_validate_fields_filled_rejects_missing_required_fields(data):
    with pytest.raises(ValidationError):
        validate_fields_filled(data)
