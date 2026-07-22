"""Unit tests for validate_and_normalize_personal_data
(bot/services/utils/personal_data.py), extracted from the inline validation
that used to live only inside RegistrationService.register(). See
test_registration_service.py for the integration-level coverage of the same
rules through the registration flow; these tests exercise the extracted
function directly."""

from datetime import datetime, timedelta

import pytest

from bot.exceptions.user_exceptions import InvalidBirthDateError, ValidationError
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.services.utils.personal_data import validate_and_normalize_personal_data


def test_valid_birth_date_and_gender_normalizes_date_format():
    birth_date, gender = validate_and_normalize_personal_data("05.03.1990", "male")

    assert birth_date == "1990-03-05"
    assert gender == "male"


@pytest.mark.parametrize("gender", ["male", "female"])
def test_valid_gender_values_pass_through_unchanged(gender):
    _, normalized_gender = validate_and_normalize_personal_data(None, gender)

    assert normalized_gender == gender


def test_none_birth_date_passes_through_as_none():
    birth_date, gender = validate_and_normalize_personal_data(None, "male")

    assert birth_date is None
    assert gender == "male"


def test_none_gender_passes_through_as_none():
    birth_date, gender = validate_and_normalize_personal_data("05.03.1990", None)

    assert birth_date == "1990-03-05"
    assert gender is None


def test_both_none_returns_both_none():
    birth_date, gender = validate_and_normalize_personal_data(None, None)

    assert birth_date is None
    assert gender is None


def test_bad_birth_date_format_raises_invalid_birth_date_error():
    with pytest.raises(InvalidBirthDateError):
        validate_and_normalize_personal_data("not-a-date", None)


def test_future_birth_date_raises_invalid_birth_date_error():
    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    future_date = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        validate_and_normalize_personal_data(future_date, None)


def test_age_over_120_years_raises_invalid_birth_date_error():
    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    too_old_date = now.replace(year=now.year - 121).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        validate_and_normalize_personal_data(too_old_date, None)


def test_invalid_gender_value_raises_validation_error_not_birth_date_error():
    with pytest.raises(ValidationError) as exc_info:
        validate_and_normalize_personal_data(None, "other")

    # InvalidBirthDateError subclasses ValidationError, so pin the exact type
    # to prove this is genuinely the gender-branch error, not a mislabeled
    # birth-date failure.
    assert type(exc_info.value) is ValidationError
