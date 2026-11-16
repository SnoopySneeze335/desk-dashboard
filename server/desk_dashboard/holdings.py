# SPDX-License-Identifier: GPL-3.0-or-later
"""SimpleFIN account/holding models and parsing (spec §4.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

log = logging.getLogger(__name__)


def parse_decimal(value: Any) -> Decimal | None:
    """SimpleFIN sends numbers as strings; never route them through float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        value = repr(value)
    try:
        result = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


@dataclass(frozen=True)
class Holding:
    symbol: str | None
    shares: Decimal | None
    market_value: Decimal | None
    currency: str

    def to_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "shares": None if self.shares is None else str(self.shares),
            "market_value": None if self.market_value is None else str(self.market_value),
            "currency": self.currency,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Holding:
        symbol = raw.get("symbol")
        symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
        currency = raw.get("currency")
        return cls(
            symbol=symbol,
            shares=parse_decimal(raw.get("shares")),
            market_value=parse_decimal(raw.get("market_value")),
            currency=currency.strip().upper() if isinstance(currency, str) and currency else "USD",
        )


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    balance_date: datetime | None
    holdings: tuple[Holding, ...] | None  # None: no holdings array in the response

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "balance_date": None if self.balance_date is None else self.balance_date.isoformat(),
            "holdings": None if self.holdings is None else [h.to_json() for h in self.holdings],
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Account:
        bd = raw.get("balance_date")
        holdings = raw.get("holdings")
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            balance_date=datetime.fromisoformat(bd) if isinstance(bd, str) else None,
            holdings=None
            if holdings is None
            else tuple(Holding.from_json(h) for h in holdings if isinstance(h, dict)),
        )


def _epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_accounts(payload: Any) -> list[Account]:
    """Parse a SimpleFIN /accounts response. Raises ValueError on a wrong shape."""
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise ValueError("SimpleFIN response has no accounts list")
    accounts = []
    for raw in payload["accounts"]:
        if not isinstance(raw, dict):
            continue
        raw_holdings = raw.get("holdings")
        holdings = None
        if isinstance(raw_holdings, list):
            holdings = tuple(Holding.from_json(h) for h in raw_holdings if isinstance(h, dict))
        accounts.append(
            Account(
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                balance_date=_epoch(raw.get("balance-date")),
                holdings=holdings,
            )
        )
    return accounts


def select_accounts(accounts: list[Account], selectors: list[str]) -> list[Account]:
    """Apply SIMPLEFIN_ACCOUNTS.

    With no selectors, include every account that has holdings; accounts with no
    holdings (checking, credit cards) are simply not part of the portfolio. With
    selectors, an explicitly chosen account that lacks holdings is still included
    so the portfolio reports `partial`.
    """
    if not selectors:
        return [a for a in accounts if a.holdings]
    lowered = [s.lower() for s in selectors]
    return [a for a in accounts if a.id in selectors or any(s in a.name.lower() for s in lowered)]
