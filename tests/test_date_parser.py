from datetime import datetime

import pytz

from bot.services.utils.date_parser import get_current_tashkent_datetime


def test_get_current_tashkent_datetime_returns_naive_datetime():
    result = get_current_tashkent_datetime()

    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_get_current_tashkent_datetime_is_close_to_real_now():
    result = get_current_tashkent_datetime()
    real_now = datetime.now(pytz.timezone("Asia/Tashkent")).replace(tzinfo=None)

    assert abs((result - real_now).total_seconds()) < 5
