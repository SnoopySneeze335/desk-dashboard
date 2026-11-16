# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the /v1/dashboard and /healthz bodies from the store (spec §8).

Aggregates only: symbols, account names/IDs, balances and holdings never
leave this module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import daychange, market
from .config import Config
from .holdings import select_accounts
from .proxies import Proxy
from .store import Store

log = logging.getLogger(__name__)

QUOTES_STALE = timedelta(minutes=5)
HOLDINGS_STALE = timedelta(hours=36)
METRICS_STALE = timedelta(seconds=30)
CENT = Decimal("0.01")


def iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(market.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(CENT, rounding=ROUND_HALF_UP))


class Dashboard:
    def __init__(self, cfg: Config, store: Store, proxy_map: dict[str, Proxy]) -> None:
        self.cfg = cfg
        self.store = store
        self.proxy_map = proxy_map
        self.portfolio_configured = cfg.demo_mode or cfg.simplefin_access_url is not None
        self.quotes_configured = cfg.demo_mode or cfg.finnhub_api_key is not None
        self.server_configured = cfg.demo_mode or cfg.server_metrics_source != "off"

    def included_accounts(self) -> list[Any]:
        if self.store.accounts is None:
            return []
        return select_accounts(self.store.accounts, self.cfg.simplefin_accounts)

    def quote_symbols(self) -> list[str]:
        return daychange.symbols_to_quote(
            self.included_accounts(), self.proxy_map, self.cfg.cash_symbols
        )

    # --- source states -------------------------------------------------

    def holdings_state(self, now: datetime) -> str:
        s = self.store
        if not self.portfolio_configured:
            return "unconfigured"
        if s.holdings_fetched_at is None:
            return "error" if s.holdings_error else "stale"
        if now - s.holdings_fetched_at > HOLDINGS_STALE:
            return "stale"
        return "ok"

    def quotes_state(self, now: datetime) -> str:
        s = self.store
        if not self.quotes_configured:
            return "unconfigured"
        if s.quotes_polled_at is None:
            return "error" if s.quotes_error else "stale"
        if market.is_open(now) and now - s.quotes_polled_at > QUOTES_STALE:
            return "stale"
        return "ok"

    def server_state(self, now: datetime) -> str:
        s = self.store
        if not self.server_configured:
            return "unconfigured"
        if s.metrics_at is None:
            return "error" if s.metrics_error else "stale"
        if now - s.metrics_at > METRICS_STALE:
            return "stale"
        return "ok"

    # --- sections --------------------------------------------------------

    def portfolio(self, now: datetime) -> dict[str, Any]:
        mstate = market.market_state(now).as_dict()
        empty: dict[str, Any] = {
            "market": mstate,
            "day_change": None,
            "day_change_pct": None,
            "positions": {"total": 0, "priced": 0, "pending": 0},
            "as_of": {"holdings": None, "quotes": None},
        }
        holdings_state = self.holdings_state(now)
        if holdings_state == "unconfigured" or self.store.accounts is None:
            return {"status": holdings_state, **empty}

        result = daychange.compute(
            self.included_accounts(),
            self.store.quotes,
            self.proxy_map,
            self.cfg.cash_symbols,
            now,
        )
        new_unmapped = result.unmapped - self.store.warned_unmapped
        for symbol in sorted(new_unmapped):
            log.warning("no quote or fund proxy for %s; counting it as pending", symbol)
        self.store.warned_unmapped |= new_unmapped

        status = "ok"
        if result.pending or result.accounts_without_holdings:
            status = "partial"
        quotes_state = self.quotes_state(now)
        if holdings_state == "stale" or (
            quotes_state in ("stale", "error") and self.quote_symbols()
        ):
            status = "stale"

        pct = result.day_change_pct
        return {
            "status": status,
            "market": mstate,
            "day_change": None if self.cfg.hide_dollar_amounts else _round(result.day_change),
            "day_change_pct": _round(pct),
            "positions": {
                "total": result.total,
                "priced": result.priced,
                "pending": result.pending,
            },
            "as_of": {
                "holdings": iso(self.store.holdings_fetched_at),
                "quotes": iso(result.quotes_as_of),
            },
        }

    def server(self, now: datetime) -> dict[str, Any]:
        state = self.server_state(now)
        s = self.store
        has_data = state != "unconfigured" and s.metrics_at is not None
        cpu = s.cpu_smoothed() if has_data else None
        ram = s.ram_pct if has_data else None
        return {
            "status": state,
            "name": self.cfg.server_display_name,
            "cpu_pct": None if cpu is None else round(cpu, 1),
            "ram_pct": None if ram is None else round(ram, 1),
            "as_of": iso(s.metrics_at) if has_data else None,
        }

    def body(self, now: datetime) -> dict[str, Any]:
        return {
            "generated_at": iso(now),
            "portfolio": self.portfolio(now),
            "server": self.server(now),
        }

    def health(self, now: datetime) -> dict[str, Any]:
        return {
            "ok": True,
            "sources": {
                "simplefin": self.holdings_state(now),
                "finnhub": self.quotes_state(now),
                "server": self.server_state(now),
            },
        }
