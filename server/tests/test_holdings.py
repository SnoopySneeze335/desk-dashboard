# SPDX-License-Identifier: GPL-3.0-or-later
from decimal import Decimal
from typing import Any

import pytest

from desk_dashboard.holdings import parse_accounts, parse_decimal, select_accounts


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12000.00", Decimal("12000.00")),
        ("20.000", Decimal("20.000")),
        (" -1.5 ", Decimal("-1.5")),
        ("1,234.50", Decimal("1234.50")),
        (5, Decimal(5)),
        (0.1, Decimal("0.1")),
        ("", None),
        ("abc", None),
        (None, None),
        ("NaN", None),
        (True, None),
    ],
)
def test_parse_decimal(raw: Any, expected: Decimal | None) -> None:
    assert parse_decimal(raw) == expected


def test_parse_accounts(accounts_payload: dict[str, Any]) -> None:
    accounts = parse_accounts(accounts_payload)
    assert [a.id for a in accounts] == ["ACT-0001", "ACT-0002", "ACT-0003"]
    brokerage = accounts[0]
    assert brokerage.holdings is not None
    assert brokerage.holdings[0].symbol == "VFIAX"
    assert brokerage.holdings[0].shares == Decimal("20.000")
    assert brokerage.holdings[0].market_value == Decimal("12000.00")
    assert accounts[1].holdings is None
    assert accounts[2].holdings == ()


def test_parse_accounts_rejects_bad_shape() -> None:
    with pytest.raises(ValueError, match="accounts"):
        parse_accounts({"nope": []})


def test_default_selection_only_accounts_with_holdings(accounts_payload: dict[str, Any]) -> None:
    accounts = parse_accounts(accounts_payload)
    assert [a.id for a in select_accounts(accounts, [])] == ["ACT-0001"]


def test_selection_by_id_and_name(accounts_payload: dict[str, Any]) -> None:
    accounts = parse_accounts(accounts_payload)
    picked = select_accounts(accounts, ["ACT-0001", "checking"])
    assert [a.id for a in picked] == ["ACT-0001", "ACT-0002"]


def test_account_round_trip(accounts_payload: dict[str, Any]) -> None:
    from desk_dashboard.holdings import Account

    for account in parse_accounts(accounts_payload):
        assert Account.from_json(account.to_json()) == account
