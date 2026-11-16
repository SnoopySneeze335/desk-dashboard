# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime
from decimal import Decimal
from typing import Any

from desk_dashboard.daychange import compute, symbols_to_quote
from desk_dashboard.holdings import Account, Holding, parse_accounts, select_accounts
from desk_dashboard.proxies import Proxy
from desk_dashboard.quote import Quote, parse_quote
from tests.conftest import ny

PROXIES = {"VFIAX": Proxy("VOO")}
CASH = frozenset({"SWVXX"})
D = Decimal


def q(d: str, pc: str, t: datetime) -> Quote:
    dp = D(d) / D(pc) * 100
    return Quote(c=D(pc) + D(d), d=D(d), dp=dp, pc=D(pc), t=t)


def brokerage(payload: dict[str, Any]) -> list[Account]:
    return select_accounts(parse_accounts(payload), [])


def test_symbols_to_quote(accounts_payload: dict[str, Any]) -> None:
    symbols = symbols_to_quote(brokerage(accounts_payload), PROXIES, CASH)
    assert symbols == ["FAKE", "VOO", "ZZZZX"]


def test_mixed_portfolio_during_session(accounts_payload: dict[str, Any]) -> None:
    now = ny(2026, 11, 16, 11, 0)
    quotes = {
        "FAKE": q("1.50", "100", now),
        "VOO": Quote(c=D("505"), d=D("5"), dp=D("1.0"), pc=D("500"), t=now),
        "ZZZZX": None,  # Finnhub can't price this mutual fund
    }
    r = compute(brokerage(accounts_payload), quotes, PROXIES, CASH, now)
    # stock 10 * 1.50 = 15; fund 12000 * 1% = 120; cash 0; ZZZZX pending
    assert r.day_change == D("135.00")
    assert r.base == D("13500.00")
    assert r.day_change_pct == D(1)
    assert (r.total, r.priced, r.pending) == (4, 3, 1)
    assert r.unmapped == {"ZZZZX"}
    assert r.quotes_as_of == now


def test_post_close_balance_backs_out_days_move() -> None:
    now = ny(2026, 11, 16, 20, 0)
    account = Account(
        "A", "Brokerage", ny(2026, 11, 16, 18, 0), (Holding("VFIAX", D(20), D("12120"), "USD"),)
    )
    quotes: dict[str, Quote | None] = {
        "VOO": Quote(c=D("505"), d=D("5"), dp=D("1.0"), pc=D("500"), t=ny(2026, 11, 16, 16, 0))
    }
    r = compute([account], quotes, PROXIES, CASH, now)
    assert r.base == D("12000")
    assert r.day_change == D("120")


def test_pre_close_balance_is_the_base() -> None:
    now = ny(2026, 11, 16, 20, 0)
    account = Account(
        "A", "Brokerage", ny(2026, 11, 16, 6, 0), (Holding("VFIAX", D(20), D("12000"), "USD"),)
    )
    quotes: dict[str, Quote | None] = {
        "VOO": Quote(c=D("505"), d=D("5"), dp=D("1.0"), pc=D("500"), t=ny(2026, 11, 16, 16, 0))
    }
    r = compute([account], quotes, PROXIES, CASH, now)
    assert r.base == D("12000")
    assert r.day_change == D("120")


def test_early_close_back_out_uses_1pm_close() -> None:
    now = ny(2026, 11, 27, 15, 0)
    account = Account(
        "A", "Brokerage", ny(2026, 11, 27, 14, 0), (Holding("VFIAX", D(1), D("101"), "USD"),)
    )
    quotes: dict[str, Quote | None] = {
        "VOO": Quote(c=D("101"), d=D("1"), dp=D("1"), pc=D("100"), t=ny(2026, 11, 27, 13, 0))
    }
    r = compute([account], quotes, PROXIES, CASH, now)
    assert r.base == D("100")


def test_quote_from_older_session_is_pending() -> None:
    now = ny(2026, 11, 16, 11, 0)
    account = Account("A", "B", None, (Holding("FAKE", D(10), D(1000), "USD"),))
    quotes = {"FAKE": q("1", "100", ny(2026, 11, 13, 16, 0))}
    r = compute([account], quotes, PROXIES, CASH, now)
    assert (r.priced, r.pending) == (0, 1)
    assert r.day_change_pct is None
    assert r.unmapped == set()


def test_unpolled_symbol_is_pending_without_warning() -> None:
    now = ny(2026, 11, 16, 11, 0)
    account = Account("A", "B", None, (Holding("FAKE", D(10), D(1000), "USD"),))
    r = compute([account], {}, PROXIES, CASH, now)
    assert r.pending == 1
    assert r.unmapped == set()


def test_cash_like_classification() -> None:
    now = ny(2026, 11, 16, 11, 0)
    account = Account(
        "A",
        "B",
        None,
        (
            Holding(None, None, D("250.00"), "USD"),  # no symbol
            Holding("SWVXX", D(100), D("100"), "USD"),  # CASH_SYMBOLS
            Holding("MMKTX", D(1000), D("1004.00"), "USD"),  # ~$1.00 per share, unpriceable
            Holding("NOTCASH", D(1000), D("1010.00"), "USD"),  # $1.01: outside 0.5%
        ),
    )
    quotes: dict[str, Quote | None] = {"MMKTX": None, "NOTCASH": None}
    r = compute([account], quotes, PROXIES, CASH, now)
    assert r.base == D("1354.00")
    assert r.day_change == 0
    assert (r.priced, r.pending) == (3, 1)
    assert r.unmapped == {"NOTCASH"}


def test_account_without_holdings_counts() -> None:
    now = ny(2026, 11, 16, 11, 0)
    r = compute([Account("A", "B", None, None)], {}, PROXIES, CASH, now)
    assert r.accounts_without_holdings == 1


def test_non_usd_is_pending() -> None:
    now = ny(2026, 11, 16, 11, 0)
    account = Account("A", "B", None, (Holding("FAKE", D(1), D(10), "CAD"),))
    r = compute([account], {"FAKE": q("1", "10", now)}, PROXIES, CASH, now)
    assert r.pending == 1


def test_negative_change() -> None:
    now = ny(2026, 11, 16, 11, 0)
    account = Account("A", "B", None, (Holding("FAKE", D("3.5"), D(350), "USD"),))
    r = compute([account], {"FAKE": q("-2.25", "100", now)}, PROXIES, CASH, now)
    assert r.day_change == D("-7.875")
    assert r.day_change_pct == D("-2.25")


def test_parse_quote_zero_and_null() -> None:
    assert (
        parse_quote({"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0})
        is None
    )
    assert parse_quote({"c": 10, "d": None, "dp": None, "pc": 10, "t": 1794603600}) is None
    assert parse_quote({}) is None
    assert parse_quote(None) is None
    assert parse_quote({"error": "bad"}) is None


def test_parse_quote_valid() -> None:
    quote = parse_quote(
        {
            "c": 371.11,
            "d": -1.51,
            "dp": -0.4052,
            "h": 374.23,
            "l": 367.99,
            "o": 374.15,
            "pc": 372.62,
            "t": 1794603600,
        }
    )
    assert quote is not None
    assert quote.d == D("-1.51")
    assert quote.pc == D("372.62")
    assert quote.t == ny(2026, 11, 13, 16, 0)
