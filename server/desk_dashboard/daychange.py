# SPDX-License-Identifier: GPL-3.0-or-later
"""Day-change classification and math (spec §5)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from . import market
from .holdings import Account, Holding
from .proxies import Proxy
from .quote import Quote

ZERO = Decimal(0)
HUNDRED = Decimal(100)
CASH_TOLERANCE = Decimal("0.005")


# Quote maps: a missing key means "not polled yet"; a None value means Finnhub
# answered but the symbol is unpriceable (mutual fund, typo, delisted).


@dataclass
class PortfolioResult:
    day_change: Decimal = ZERO
    base: Decimal = ZERO
    total: int = 0
    priced: int = 0
    pending: int = 0
    accounts_without_holdings: int = 0
    unmapped: set[str] = field(default_factory=set)
    quotes_as_of: datetime | None = None

    @property
    def day_change_pct(self) -> Decimal | None:
        if self.base == ZERO:
            return None
        return HUNDRED * self.day_change / self.base


def looks_like_cash(h: Holding) -> bool:
    if h.shares is None or h.market_value is None or h.shares == ZERO:
        return False
    return abs(h.market_value / h.shares - 1) <= CASH_TOLERANCE


def quote_symbol(h: Holding, proxy_map: Mapping[str, Proxy], cash: frozenset[str]) -> str | None:
    """The symbol whose quote prices this holding, or None if no quote is needed."""
    if h.symbol is None or h.symbol in cash:
        return None
    proxy = proxy_map.get(h.symbol)
    return proxy.symbol if proxy else h.symbol


def symbols_to_quote(
    accounts: Iterable[Account], proxy_map: Mapping[str, Proxy], cash: frozenset[str]
) -> list[str]:
    symbols = {
        sym
        for a in accounts
        for h in a.holdings or ()
        if (sym := quote_symbol(h, proxy_map, cash)) is not None
    }
    return sorted(symbols)


def _fresh(q: Quote | None, session: date) -> Quote | None:
    if q is None or market.session_of(q.t) != session:
        return None
    return q


def compute(
    accounts: Iterable[Account],
    quotes: Mapping[str, Quote | None],
    proxy_map: Mapping[str, Proxy],
    cash: frozenset[str],
    now: datetime,
) -> PortfolioResult:
    session = market.market_state(now).session_date
    result = PortfolioResult()

    for account in accounts:
        if account.holdings is None:
            result.accounts_without_holdings += 1
            continue
        for h in account.holdings:
            result.total += 1
            delta, base, used = _classify(h, account, quotes, proxy_map, cash, session, result)
            if delta is None or base is None:
                result.pending += 1
                continue
            result.priced += 1
            result.day_change += delta
            result.base += base
            if used is not None and (result.quotes_as_of is None or used.t > result.quotes_as_of):
                result.quotes_as_of = used.t
    return result


def _classify(
    h: Holding,
    account: Account,
    quotes: Mapping[str, Quote | None],
    proxy_map: Mapping[str, Proxy],
    cash: frozenset[str],
    session: date,
    result: PortfolioResult,
) -> tuple[Decimal | None, Decimal | None, Quote | None]:
    if h.currency != "USD":
        return None, None, None
    if h.symbol is None or h.symbol in cash:
        return ZERO, h.market_value or ZERO, None

    proxy = proxy_map.get(h.symbol)
    if proxy is not None:
        q = _fresh(quotes.get(proxy.symbol), session)
        if q is None or h.market_value is None:
            return None, None, None
        base = h.market_value
        close = market.session_close(market.session_of(q.t))
        if account.balance_date is not None and account.balance_date >= close:
            base = h.market_value / (1 + q.dp / HUNDRED)
        return base * q.dp / HUNDRED, base, q

    if h.symbol not in quotes:  # not polled yet
        return None, None, None
    own = quotes[h.symbol]
    q = _fresh(own, session)
    if q is not None and h.shares is not None:
        return h.shares * q.d, h.shares * q.pc, q
    if own is None:  # Finnhub can't price it
        if looks_like_cash(h):
            return ZERO, h.market_value or ZERO, None
        result.unmapped.add(h.symbol)
    return None, None, None
