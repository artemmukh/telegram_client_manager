import pytest

from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    CALENDAR_MAX_YEAR,
    CALENDAR_MIN_YEAR,
    WEEKDAY_LABELS_RU,
    clamp_calendar_date,
    clamp_month_to_range,
    format_calendar_date_display,
    format_month_label,
    generate_month_days,
    get_month_grid,
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


def test_clamp_month_to_range_clamps_month_above_twelve():
    assert clamp_month_to_range(2026, 13) == (2026, 12)


def test_clamp_month_to_range_clamps_month_below_one():
    assert clamp_month_to_range(2026, 0) == (2026, 1)


# --- clamp_calendar_date ---

def test_clamp_calendar_date_clamps_day_above_month_length():
    assert clamp_calendar_date(2026, 2, 31) == (2026, 2, 28)


def test_clamp_calendar_date_clamps_month_above_twelve():
    assert clamp_calendar_date(2026, 13, 5) == (2026, 12, 5)


def test_clamp_calendar_date_clamps_year_below_range():
    assert clamp_calendar_date(2025, 12, 31) == (2026, 1, 31)


def test_clamp_calendar_date_leaves_in_range_date_untouched():
    assert clamp_calendar_date(2026, 7, 17) == (2026, 7, 17)


def test_clamp_calendar_date_clamps_day_below_one():
    assert clamp_calendar_date(2026, 7, 0) == (2026, 7, 1)


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


# --- get_month_grid ---

def test_get_month_grid_july_2026_starts_with_two_leading_days_from_june():
    grid = get_month_grid(2026, 7)

    assert grid[0] == (29, 2026, 6)
    assert grid[1] == (30, 2026, 6)
    assert grid[2] == (1, 2026, 7)


@pytest.mark.parametrize(
    "year, month",
    [
        (2026, 1),
        (2026, 2),
        (2026, 7),
        (2026, 12),
        (2027, 1),
        (2027, 6),
        (2027, 12),
    ],
)
def test_get_month_grid_length_is_always_a_multiple_of_seven(year, month):
    grid = get_month_grid(year, month)

    assert len(grid) % 7 == 0


def test_get_month_grid_month_starting_on_monday_has_no_leading_days():
    # 2026-06-01 is a Monday (datetime(2026, 6, 1).weekday() == 0).
    grid = get_month_grid(2026, 6)

    assert grid[0] == (1, 2026, 6)


def test_get_month_grid_december_2026_trailing_days_belong_to_january_2027():
    grid = get_month_grid(2026, 12)
    trailing = [cell for cell in grid if cell[1:] == (2027, 1)]

    assert trailing == [(1, 2027, 1), (2, 2027, 1), (3, 2027, 1)]


def test_get_month_grid_december_2027_trailing_days_use_true_next_month_not_circular_wrap():
    """get_month_grid's arithmetic for the trailing edge is plain calendar math -
    unlike shift_month, it must NOT wrap circularly back to CALENDAR_MIN_YEAR.
    December 2027's trailing days belong to January 2028, not January 2026."""
    grid = get_month_grid(2027, 12)
    trailing = [cell for cell in grid if cell[0] <= 3 and cell[2] == 1]

    assert trailing == [(1, 2028, 1), (2, 2028, 1)]
    assert all(cell[1] == 2028 for cell in trailing)


# --- appointment_calendar_kb ---

def test_appointment_calendar_kb_includes_a_button_for_every_day():
    markup = appointment_calendar_kb(2026, 7)
    callback_datas = _callback_datas(markup)

    for day in range(1, 32):
        assert ApptCalendarDayCB(year=2026, month=7, day=day).pack() in callback_datas


def test_appointment_calendar_kb_first_row_is_weekday_header():
    markup = appointment_calendar_kb(2026, 7)
    header_row = markup.inline_keyboard[0]

    assert [button.text for button in header_row] == WEEKDAY_LABELS_RU
    assert all(button.callback_data == "noop" for button in header_row)


def test_appointment_calendar_kb_week_rows_are_full_seven_wide_with_no_remainder():
    markup = appointment_calendar_kb(2026, 7)
    week_rows = markup.inline_keyboard[1:-3]

    assert len(week_rows) > 0
    assert all(len(row) == 7 for row in week_rows)


def test_appointment_calendar_kb_leading_days_carry_their_own_month_not_displayed_month():
    """June 29/30 are the two leading (out-of-current-month) cells rendered
    inside the July 2026 grid. Their callback data must pack the CELL's own
    year/month (June), not the displayed month (July) - otherwise clicking
    them would resolve to the wrong month's appointments."""
    markup = appointment_calendar_kb(2026, 7)
    callback_datas = _callback_datas(markup)

    assert ApptCalendarDayCB(year=2026, month=6, day=29).pack() in callback_datas
    assert ApptCalendarDayCB(year=2026, month=6, day=30).pack() in callback_datas

    # July's own days 29 and 30 must be distinct buttons from the leading
    # June cells above - both should be present (July has 31 days), proving
    # the two "29"/"30" texts on screen resolve to different callback data.
    assert ApptCalendarDayCB(year=2026, month=7, day=29).pack() in callback_datas
    assert ApptCalendarDayCB(year=2026, month=7, day=30).pack() in callback_datas
    assert callback_datas.count(ApptCalendarDayCB(year=2026, month=6, day=29).pack()) == 1
    assert callback_datas.count(ApptCalendarDayCB(year=2026, month=7, day=29).pack()) == 1

    # Adjacent-month cells (June 29/30 shown inside July's grid) get a "·"
    # prefix on their button text to visually mark them as belonging to a
    # different month than the one being displayed - even though they are
    # in-range and clickable. July's own 29/30 stay plain.
    buttons_by_callback_data = {button.callback_data: button for button in _all_buttons(markup)}
    june_29 = buttons_by_callback_data[ApptCalendarDayCB(year=2026, month=6, day=29).pack()]
    june_30 = buttons_by_callback_data[ApptCalendarDayCB(year=2026, month=6, day=30).pack()]
    july_29 = buttons_by_callback_data[ApptCalendarDayCB(year=2026, month=7, day=29).pack()]
    july_30 = buttons_by_callback_data[ApptCalendarDayCB(year=2026, month=7, day=30).pack()]

    assert june_29.text == "·29"
    assert june_30.text == "·30"
    assert july_29.text == "29"
    assert july_30.text == "30"


def test_appointment_calendar_kb_leading_days_render_as_noop_at_min_year_boundary():
    """January 2026 = CALENDAR_MIN_YEAR: its leading cells belong to December
    2025, which is out of range, so they must render as non-interactive noop
    buttons despite still showing a day number as text."""
    markup = appointment_calendar_kb(2026, 1)
    day_buttons = [button for row in markup.inline_keyboard[1:-3] for button in row]
    grid = get_month_grid(2026, 1)

    out_of_range_buttons = [
        button for button, (day, cell_year, cell_month) in zip(day_buttons, grid)
        if clamp_month_to_range(cell_year, cell_month) != (cell_year, cell_month)
    ]

    assert out_of_range_buttons
    for button in out_of_range_buttons:
        assert button.callback_data == "noop"
        # These cells belong to December 2025 (an adjacent month relative to
        # the displayed January 2026), so they carry the "·" adjacent-month
        # prefix in addition to being non-interactive.
        assert button.text.startswith("·")
        assert button.text[1:].isdigit()


def test_appointment_calendar_kb_trailing_days_render_as_noop_at_max_year_boundary():
    """December 2027 = CALENDAR_MAX_YEAR: its trailing cells belong to
    January 2028, which is out of range, so they must render as
    non-interactive noop buttons despite still showing a day number as text."""
    markup = appointment_calendar_kb(2027, 12)
    day_buttons = [button for row in markup.inline_keyboard[1:-3] for button in row]
    grid = get_month_grid(2027, 12)

    out_of_range_buttons = [
        button for button, (day, cell_year, cell_month) in zip(day_buttons, grid)
        if clamp_month_to_range(cell_year, cell_month) != (cell_year, cell_month)
    ]

    assert out_of_range_buttons
    for button in out_of_range_buttons:
        assert button.callback_data == "noop"
        # These cells belong to January 2028 (an adjacent month relative to
        # the displayed December 2027), so they carry the "·" adjacent-month
        # prefix in addition to being non-interactive.
        assert button.text.startswith("·")
        assert button.text[1:].isdigit()


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
