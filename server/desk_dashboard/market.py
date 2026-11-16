# SPDX-License-Identifier: GPL-3.0-or-later
"""NYSE calendar and market state (spec §7).

Rules-based so it needs no yearly data file. Unscheduled closures (for example
a national day of mourning) are listed in SPECIAL_CLOSURES as they happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

SPECIAL_CLOSURES = frozenset({date(2018, 12, 5), date(2025, 1, 9)})


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    days = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    # NYSE doesn't observe New Year's Day on the prior Friday when it falls on a Saturday.
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        days.add(new_year + timedelta(days=1))
    elif new_year.weekday() < 5:
        days.add(new_year)
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    days.update(d for d in SPECIAL_CLOSURES if d.year == year)
    return frozenset(days)


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def is_early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    july3 = date(d.year, 7, 3)
    if d == july3 and d.weekday() < 4:  # Mon-Thu; a Friday July 3 is the observed holiday
        return True
    if d == _nth_weekday(d.year, 11, 3, 4) + timedelta(days=1):
        return True
    return d == date(d.year, 12, 24)


def close_time(d: date) -> time:
    return EARLY_CLOSE if is_early_close(d) else CLOSE


def session_open(d: date) -> datetime:
    return datetime.combine(d, OPEN, NY)


def session_close(d: date) -> datetime:
    return datetime.combine(d, close_time(d), NY)


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def session_of(ts: datetime) -> date:
    """The trading session a trade timestamp belongs to."""
    local = ts.astimezone(NY)
    d = local.date()
    if is_trading_day(d) and local >= session_open(d):
        return d
    return previous_trading_day(d)


@dataclass(frozen=True)
class MarketState:
    state: str  # open | pre | closed | weekend | holiday
    session_date: date
    label: str

    def as_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "session_date": self.session_date.isoformat(),
            "label": self.label,
        }


def _close_label(d: date) -> str:
    return f"{d.strftime('%a')} close"


def market_state(now: datetime) -> MarketState:
    local = now.astimezone(NY)
    today = local.date()
    if not is_trading_day(today):
        state = "weekend" if today.weekday() >= 5 else "holiday"
        session = previous_trading_day(today)
        return MarketState(state, session, _close_label(session))
    if local < session_open(today):
        session = previous_trading_day(today)
        return MarketState("pre", session, _close_label(session))
    if local < session_close(today):
        return MarketState("open", today, "Live")
    return MarketState("closed", today, _close_label(today))


def is_open(now: datetime) -> bool:
    return market_state(now).state == "open"


def next_open(now: datetime) -> datetime:
    local = now.astimezone(NY)
    d = local.date()
    if is_trading_day(d) and local < session_open(d):
        return session_open(d)
    return session_open(next_trading_day(d))
