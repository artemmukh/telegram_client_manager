import pytest

from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    CALENDAR_MAX_YEAR,
    CALENDAR_MIN_YEAR,
    clamp_month_to_range,
    format_calendar_date_display,
    format_month_label,
    generate_month_days,
    shift_month,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_calendar_kb,
    appointment_list_kb,
)


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def _callback_datas(markup):
    return [button.callback_data for button in _all_buttons(markup)]


# --- clamp_month_to_range ---

def test_clamp_month_to_range_leaves_in_range_month_untouched():
    assert clamp_month_to_range(2026, 7) == (2026, 7)
    assert clamp_month_to_range(2027, 12) == (2027, 12)


def test_clamp_month_to_range_clamps_below_range_to_january_2026():
    assert clamp_month_to_range(2025, 12) == (CALENDAR_MIN_YEAR, 1)


def test_clamp_month_to_range_clamps_above_range_to_december_2027():
    assert clamp_month_to_range(2028, 1) == (CALENDAR_MAX_YEAR, 12)


# --- shift_month ---

def test_shift_month_next_moves_forward_within_same_year():
    assert shift_month(2026, 7, "next") == (2026, 8)


def test_shift_month_prev_moves_backward_within_same_year():
    assert shift_month(2026, 7, "prev") == (2026, 6)


def test_shift_month_next_crosses_year_boundary():
    assert shift_month(2026, 12, "next") == (2027, 1)


def test_shift_month_prev_crosses_year_boundary():
    assert shift_month(2027, 1, "prev") == (2026, 12)


def test_shift_month_next_wraps_circularly_from_max_to_min():
    assert shift_month(2027, 12, "next") == (2026, 1)


def test_shift_month_prev_wraps_circularly_from_min_to_max():
    assert shift_month(2026, 1, "prev") == (2027, 12)


def test_shift_month_unknown_direction_raises():
    with pytest.raises(ValueError):
        shift_month(2026, 7, "sideways")


# --- generate_month_days / format_month_label / format_calendar_date_display ---

def test_generate_month_days_returns_correct_count_for_31_day_month():
    assert generate_month_days(2026, 7) == list(range(1, 32))


def test_generate_month_days_returns_correct_count_for_february_non_leap_year():
    assert generate_month_days(2026, 2) == list(range(1, 29))


def test_format_month_label_uses_nominative_russian_month_name():
    assert format_month_label(2026, 7) == "Июль 2026"


def test_format_calendar_date_display_formats_iso_date_as_ddmmyyyy():
    assert format_calendar_date_display("2026-07-17") == "17.07.2026"


# --- appointment_calendar_kb ---

def test_appointment_calendar_kb_includes_a_button_for_every_day():
    markup = appointment_calendar_kb(2026, 7)
    callback_datas = _callback_datas(markup)

    for day in range(1, 32):
        assert ApptCalendarDayCB(year=2026, month=7, day=day).pack() in callback_datas


def test_appointment_calendar_kb_month_row_is_seven_per_row_with_remainder_last():
    markup = appointment_calendar_kb(2026, 7)
    day_rows = markup.inline_keyboard[:-3]

    assert [len(row) for row in day_rows[:-1]] == [7] * (len(day_rows) - 1)
    assert len(day_rows[-1]) == 31 - 7 * (len(day_rows) - 1)


def test_appointment_calendar_kb_has_noop_month_label():
    markup = appointment_calendar_kb(2026, 7)
    label_row = markup.inline_keyboard[-3]

    assert len(label_row) == 1
    assert label_row[0].text == "Июль 2026"
    assert label_row[0].callback_data == "noop"


def test_appointment_calendar_kb_nav_row_targets_adjacent_months():
    markup = appointment_calendar_kb(2026, 7)
    nav_row = markup.inline_keyboard[-2]
    callback_datas = [button.callback_data for button in nav_row]

    assert ApptCalendarMonthCB(year=2026, month=6).pack() in callback_datas
    assert ApptCalendarMonthCB(year=2026, month=8).pack() in callback_datas


def test_appointment_calendar_kb_nav_wraps_circularly_at_range_boundaries():
    markup = appointment_calendar_kb(2027, 12)
    nav_row = markup.inline_keyboard[-2]
    callback_datas = [button.callback_data for button in nav_row]

    assert ApptCalendarMonthCB(year=2027, month=11).pack() in callback_datas
    assert ApptCalendarMonthCB(year=2026, month=1).pack() in callback_datas


def test_appointment_calendar_kb_back_row_returns_to_search_menu():
    markup = appointment_calendar_kb(2026, 7)
    back_row = markup.inline_keyboard[-1]

    assert len(back_row) == 1
    assert back_row[0].callback_data == "browse_appointments"


# --- appointment_list_kb back-navigation params ---

def test_appointment_list_kb_defaults_back_button_to_search_menu():
    markup = appointment_list_kb([], "list", 1, 1, "confirmed")
    back_row = markup.inline_keyboard[-1]

    assert back_row[0].text == "⬅️ К меню поиска"
    assert back_row[0].callback_data == "browse_appointments"


def test_appointment_list_kb_calendar_mode_can_override_back_button():
    back_target = ApptCalendarMonthCB(year=2026, month=7).pack()
    markup = appointment_list_kb(
        [], "calendar", 1, 1, "confirmed",
        back_callback_data=back_target, back_label="⬅️ К календарю",
    )
    back_row = markup.inline_keyboard[-1]

    assert back_row[0].text == "⬅️ К календарю"
    assert back_row[0].callback_data == back_target
