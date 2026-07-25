"""Tests for bot.services.document_generator.pydocx's tooth-map lookups.

find_tooth/find_marker must operate on a plain string (the original bug fixed
by this feature passed a list into these, e.g. data.get(['diagnosis']) instead
of data.get("diagnosis"), causing TypeError: unhashable type: 'list').
"""

from bot.services.document_generator.pydocx import find_marker, find_tooth


def test_find_tooth_extracts_two_digit_tooth_number():
    assert find_tooth("Средний кариес 37 зуба") == 37


def test_find_tooth_returns_none_when_no_tooth_number_present():
    assert find_tooth("Консультация") is None


def test_find_tooth_ignores_numbers_outside_the_valid_quadrant_range():
    # Valid FDI tooth numbers are 11-48 with the first digit in 1-4 and the
    # second in 1-8 -- "99" and "50" must not match.
    assert find_tooth("Запись №99, талон 50") is None


def test_find_marker_recognizes_karies():
    assert find_marker("Средний кариес 37 зуба") == "C"


def test_find_marker_recognizes_pulpit():
    assert find_marker("Острый пульпит 46 зуба") == "P"


def test_find_marker_recognizes_udalenie():
    assert find_marker("Удаление 18 зуба по показаниям") == "X"


def test_find_marker_is_case_insensitive():
    assert find_marker("КАРИЕС 21 зуба") == "C"


def test_find_marker_returns_empty_string_when_no_keyword_matches():
    assert find_marker("Консультация") == ""


def test_find_tooth_and_find_marker_accept_plain_strings_not_lists():
    """Regression: the original bug called data.get(['diagnosis']) (a list),
    which raised TypeError: unhashable type: 'list' inside dict.get(). Passing
    a plain str must work without error for both helpers."""
    diagnosis = "Пульпит 27 зуба"

    assert isinstance(diagnosis, str)
    assert find_tooth(diagnosis) == 27
    assert find_marker(diagnosis) == "P"
