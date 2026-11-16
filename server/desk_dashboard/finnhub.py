# SPDX-License-Identifier: GPL-3.0-or-later
"""Finnhub quote client and market-hours schedule (spec §4.2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

import aiohttp

from . import market
from .quote import Quote, parse_quote
from .store import Store

log = logging.getLogger(__name__)
QUOTE_URL = "https://finnhub.io/api/v1/quote"
TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)
CALLS_PER_MINUTE = 50  # free tier allows 60; leave headroom
POST_CLOSE_DELAY = timedelta(minutes=5)


class QuoteError(Exception):
    pass


class AuthError(QuoteError):
    pass


async def fetch_quote(session: aiohttp.ClientSession, api_key: str, symbol: str) -> Quote | None:
    """Returns None when Finnhub answers but can't price the symbol."""
    headers = {"X-Finnhub-Token": api_key}
    try:
        async with session.get(
            QUOTE_URL, params={"symbol": symbol}, headers=headers, timeout=TIMEOUT
        ) as resp:
            if resp.status in (401, 403):
                raise AuthError(f"HTTP {resp.status}: check FINNHUB_API_KEY")
            if resp.status != 200:
                raise QuoteError(f"HTTP {resp.status}")
            payload = await resp.json(content_type=None)
    except aiohttp.ClientError as exc:
        raise QuoteError(f"network error: {type(exc).__name__}") from None
    except TimeoutError:
        raise QuoteError("timed out") from None
    return parse_quote(payload)


def next_quote_wake(now: datetime, interval: int, post_close_done: date | None) -> datetime:
    """When the next quote poll should run (regular session, plus once after close)."""
    st = market.market_state(now)
    today = now.astimezone(market.NY).date()
    if st.state == "open":
        after_close = market.session_close(today) + POST_CLOSE_DELAY
        return min(now + timedelta(seconds=interval), after_close)
    if st.state == "closed" and post_close_done != today:
        return max(now, market.session_close(today) + POST_CLOSE_DELAY)
    return market.next_open(now)


class QuotePoller:
    def __init__(
        self,
        api_key: str,
        interval: int,
        store: Store,
        symbols: Callable[[], list[str]],
        session: aiohttp.ClientSession,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        spacing: float = 60 / CALLS_PER_MINUTE,
    ) -> None:
        self.api_key = api_key
        self.interval = interval
        self.store = store
        self.symbols = symbols
        self.session = session
        self.clock = clock
        self.sleep = sleep
        self.spacing = spacing
        self.trigger = asyncio.Event()
        self.post_close_done: date | None = None

    async def _one(self, symbol: str) -> tuple[bool, Quote | None]:
        delay = 2.0
        for attempt in range(3):
            try:
                return True, await fetch_quote(self.session, self.api_key, symbol)
            except AuthError:
                raise
            except QuoteError as exc:
                if attempt == 2:
                    log.warning("quote for %s failed: %s", symbol, exc)
                    return False, None
                await self.sleep(delay)
                delay *= 4
        return False, None

    async def poll(self) -> None:
        symbols = self.symbols()
        if not symbols:
            return
        results: dict[str, Quote | None] = {}
        try:
            for i, symbol in enumerate(symbols):
                if i:
                    await self.sleep(self.spacing)
                ok, quote = await self._one(symbol)
                if ok:
                    results[symbol] = quote
        except AuthError as exc:
            log.error("Finnhub rejected the API key: %s", exc)
            self.store.quotes_error = str(exc)
            return
        now = self.clock()
        if results:
            self.store.update_quotes(results, now)
            log.debug("quotes updated: %d/%d", len(results), len(symbols))
        else:
            self.store.quotes_error = "all quote requests failed"
        today = now.astimezone(market.NY).date()
        if (
            market.market_state(now).state == "closed"
            and now >= market.session_close(today) + POST_CLOSE_DELAY
        ):
            self.post_close_done = today

    async def run(self) -> None:
        await self.poll()  # once at startup
        while True:
            wake = next_quote_wake(self.clock(), self.interval, self.post_close_done)
            timeout = max(0.0, (wake - self.clock()).total_seconds())
            try:
                await asyncio.wait_for(self.trigger.wait(), timeout=timeout)
                self.trigger.clear()  # new holdings arrived
            except TimeoutError:
                pass
            await self.poll()
