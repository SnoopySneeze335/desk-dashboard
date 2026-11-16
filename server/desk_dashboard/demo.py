# SPDX-License-Identifier: GPL-3.0-or-later
"""DEMO_MODE: synthetic holdings, quotes and metrics; no network at all.

The fake data runs through the same day-change code as real data.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal

from . import market
from .holdings import Account, Holding
from .proxies import Proxy
from .quote import Quote
from .store import Store

DEMO_PROXIES = {"DEMOFUNDX": Proxy("DEMOETF")}

_D = Decimal


def demo_accounts(now: datetime) -> list[Account]:
    return [
        Account(
            id="DEMO-ACT-1",
            name="Demo Brokerage",
            balance_date=now - timedelta(hours=10),
            holdings=(
                Holding("DEMOSTK", _D("40"), _D("8000.00"), "USD"),
                Holding("DEMOETF", _D("25"), _D("10000.00"), "USD"),
                Holding("DEMOFUNDX", _D("50"), _D("12000.00"), "USD"),
                Holding("DEMOMMF", _D("1500"), _D("1500.00"), "USD"),
                Holding("DEMOUNKNX", _D("10"), _D("900.00"), "USD"),  # stays pending
            ),
        )
    ]


def _wave(now: datetime, period_s: float, phase: float = 0.0) -> float:
    return math.sin(2 * math.pi * (now.timestamp() / period_s) + phase)


def demo_quotes(now: datetime) -> dict[str, Quote | None]:
    st = market.market_state(now)
    close = market.session_close(st.session_date)
    t = min(now, close) if st.state == "open" else close
    quotes: dict[str, Quote | None] = {"DEMOMMF": None, "DEMOUNKNX": None}
    for symbol, pc, phase in (("DEMOSTK", "200.00", 0.0), ("DEMOETF", "400.00", 1.3)):
        prev = _D(pc)
        dp = _D(str(round(1.2 * _wave(now, 900, phase), 4)))
        d = (prev * dp / 100).quantize(_D("0.01"))
        quotes[symbol] = Quote(c=prev + d, d=d, dp=dp, pc=prev, t=t)
    return quotes


async def run_demo(store: Store, clock: Callable[[], datetime], window: int) -> None:
    start = clock()
    store.set_holdings(demo_accounts(start), start)
    while True:
        now = clock()
        store.update_quotes(demo_quotes(now), now)
        cpu = 30 + 18 * _wave(now, 120) + 6 * _wave(now, 17, 0.5)
        ram = 58 + 4 * _wave(now, 600, 2.0)
        store.add_metrics(round(cpu, 1), round(ram, 1), now, window)
        await asyncio.sleep(5)
