# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import date, time

import pytest

from desk_dashboard import market
from tests.conftest import ny


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 6, 18),
        date(2027, 12, 24),
        date(2028, 1, 17),
        date(2025, 1, 9),
    ],
)
def test_holidays(day: date) -> None:
    assert market.is_holiday(day)
    assert not market.is_trading_day(day)


def test_new_year_on_saturday_not_observed_friday() -> None:
    # 2022-01-01 was a Saturday; NYSE stayed open on Fri 2021-12-31.
    assert market.is_trading_day(date(2021, 12, 31))


@pytest.mark.parametrize(
    "day", [date(2026, 11, 27), date(2026, 12, 24), date(2025, 7, 3), date(2025, 11, 28)]
)
def test_early_closes(day: date) -> None:
    assert market.close_time(day) == time(13, 0)


def test_no_early_close_on_normal_day() -> None:
    assert market.close_time(date(2026, 11, 17)) == time(16, 0)


def test_weekend_state() -> None:
    st = market.market_state(ny(2026, 11, 15, 12, 0))
    assert (st.state, st.session_date, st.label) == ("weekend", date(2026, 11, 13), "Fri close")


def test_pre_state_monday() -> None:
    st = market.market_state(ny(2026, 11, 16, 8, 0))
    assert (st.state, st.session_date, st.label) == ("pre", date(2026, 11, 13), "Fri close")


def test_open_state() -> None:
    st = market.market_state(ny(2026, 11, 16, 9, 30))
    assert (st.state, st.session_date, st.label) == ("open", date(2026, 11, 16), "Live")


def test_closed_state() -> None:
    st = market.market_state(ny(2026, 11, 16, 16, 0))
    assert (st.state, st.session_date, st.label) == ("closed", date(2026, 11, 16), "Mon close")


def test_early_close_state() -> None:
    assert market.market_state(ny(2026, 11, 27, 12, 59)).state == "open"
    assert market.market_state(ny(2026, 11, 27, 13, 0)).state == "closed"


def test_holiday_state() -> None:
    st = market.market_state(ny(2026, 11, 26, 11, 0))
    assert (st.state, st.session_date, st.label) == ("holiday", date(2026, 11, 25), "Wed close")


def test_session_of_trade_times() -> None:
    assert market.session_of(ny(2026, 11, 13, 16, 0)) == date(2026, 11, 13)
    assert market.session_of(ny(2026, 11, 16, 9, 0)) == date(2026, 11, 13)
    assert market.session_of(ny(2026, 11, 14, 10, 0)) == date(2026, 11, 13)


def test_next_open() -> None:
    assert market.next_open(ny(2026, 11, 13, 17, 0)) == ny(2026, 11, 16, 9, 30)
    assert market.next_open(ny(2026, 11, 25, 17, 0)) == ny(2026, 11, 27, 9, 30)
    assert market.next_open(ny(2026, 11, 16, 7, 0)) == ny(2026, 11, 16, 9, 30)
