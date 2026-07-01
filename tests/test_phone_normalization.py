import pytest

from bot.utils.tools import normalize_phone


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("901234567", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("+998901234567", "+998901234567"),
        (" 90 123 45 67 ", "+998901234567"),
        ("(90) 123-45-67", "+998901234567"),
    ],
)
def test_normalize_phone_supported_uzbek_formats(raw_phone, expected):
    assert normalize_phone(raw_phone) == expected


def test_normalize_phone_leaves_unknown_lengths_unchanged_after_cleanup():
    assert normalize_phone("12345") == "12345"
