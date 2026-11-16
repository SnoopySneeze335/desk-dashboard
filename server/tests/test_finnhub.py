# SPDX-License-Identifier: GPL-3.0-or-later
import re
from datetime import timedelta

import aiohttp
from aioresponses import aioresponses

from desk_dashboard.finnhub import QuotePoller, fetch_quote, next_quote_wake
from desk_dashboard.store import Store
from tests.conftest import FakeClock, ny

QUOTE = re.compile(r"^https://finnhub\.io/api/v1/quote\?symbol=(\w+)$")
GOOD = {
    "c": 371.11,
    "d": -1.51,
    "dp": -0.4052,
    "h": 374.23,
    "l": 367.99,
    "o": 374.15,
    "pc": 372.62,
    "t": 1794603600,
}


async def no_sleep(_: float) -> None:
    return None


async def test_key_goes_in_header_not_url() -> None:
    with aioresponses() as m:
        m.get(QUOTE, payload=GOOD)
        async with aiohttp.ClientSession() as session:
            quote = await fetch_quote(session, "fake-finnhub-key", "FAKE")
        ((key, calls),) = m.requests.items()
        assert "fake-finnhub-key" not in str(key[1])
        assert calls[0].kwargs["headers"]["X-Finnhub-Token"] == "fake-finnhub-key"
    assert quote is not None


async def test_zero_quote_is_unpriceable() -> None:
    with aioresponses() as m:
        m.get(
            QUOTE, payload={"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
        )
        async with aiohttp.ClientSession() as session:
            assert await fetch_quote(session, "k", "VFIAX") is None


async def test_poll_keeps_old_quote_on_network_failure() -> None:
    clock = FakeClock(ny(2026, 11, 16, 11, 0))
    store = Store()
    with aioresponses() as m:
        m.get(QUOTE, payload=GOOD)
        m.get(QUOTE, payload={"c": 0, "pc": 0, "d": None, "dp": None, "t": 0})
        async with aiohttp.ClientSession() as session:
            poller = QuotePoller(
                "k", 60, store, lambda: ["AAA", "BBB"], session, clock, sleep=no_sleep, spacing=0
            )
            await poller.poll()
            assert store.quotes["AAA"] is not None
            assert store.quotes["BBB"] is None
            first = store.quotes["AAA"]

            m.get(QUOTE, exception=aiohttp.ClientConnectionError(), repeat=True)
            clock.now += timedelta(minutes=1)
            await poller.poll()
    assert store.quotes["AAA"] is first
    assert store.quotes_error == "all quote requests failed"
    assert store.quotes_polled_at == ny(2026, 11, 16, 11, 0)


async def test_bad_key_stops_poll() -> None:
    clock = FakeClock(ny(2026, 11, 16, 11, 0))
    store = Store()
    with aioresponses() as m:
        m.get(QUOTE, status=401, repeat=True)
        async with aiohttp.ClientSession() as session:
            poller = QuotePoller(
                "k", 60, store, lambda: ["AAA", "BBB"], session, clock, sleep=no_sleep, spacing=0
            )
            await poller.poll()
        assert sum(len(c) for c in m.requests.values()) == 1
    assert store.quotes_error is not None and "401" in store.quotes_error


def test_schedule_during_session() -> None:
    now = ny(2026, 11, 16, 11, 0)
    assert next_quote_wake(now, 60, None) == now + timedelta(seconds=60)


def test_schedule_post_close_poll() -> None:
    assert next_quote_wake(ny(2026, 11, 16, 15, 59, 30), 60, None) == ny(2026, 11, 16, 16, 0, 30)
    assert next_quote_wake(ny(2026, 11, 16, 16, 1), 60, None) == ny(2026, 11, 16, 16, 5)
    done = ny(2026, 11, 16).date()
    assert next_quote_wake(ny(2026, 11, 16, 16, 6), 60, done) == ny(2026, 11, 17, 9, 30)


def test_schedule_weekend_and_holiday() -> None:
    assert next_quote_wake(ny(2026, 11, 14, 12, 0), 60, None) == ny(2026, 11, 16, 9, 30)
    assert next_quote_wake(ny(2026, 11, 26, 12, 0), 60, None) == ny(2026, 11, 27, 9, 30)
    assert next_quote_wake(ny(2026, 11, 16, 7, 0), 60, None) == ny(2026, 11, 16, 9, 30)


def test_schedule_early_close() -> None:
    assert next_quote_wake(ny(2026, 11, 27, 13, 2), 60, None) == ny(2026, 11, 27, 13, 5)
