# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import re
from datetime import time, timedelta
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from desk_dashboard.logsetup import RedactingFilter, register_secret
from desk_dashboard.quota import QuotaGuard
from desk_dashboard.simplefin import (
    HoldingsCache,
    SimpleFinError,
    SimpleFinPoller,
    fetch_accounts,
    next_fetch_time,
    split_access_url,
)
from desk_dashboard.store import Store
from tests.conftest import FakeClock, ny

ACCESS_URL = "https://fakeuser:fakepass@bridge.example.invalid/simplefin"
ACCOUNTS = re.compile(r"^https://bridge\.example\.invalid/simplefin/accounts(\?.*)?$")


async def no_sleep(_: float) -> None:
    return None


def test_split_access_url_removes_credentials() -> None:
    url, auth = split_access_url(ACCESS_URL)
    assert str(url) == "https://bridge.example.invalid/simplefin"
    assert auth is not None
    assert (auth.login, auth.password) == ("fakeuser", "fakepass")


async def test_fetch_sends_basic_auth_and_small_window(accounts_payload: dict[str, Any]) -> None:
    now = ny(2026, 11, 16, 6, 0)
    with aioresponses() as m:
        m.get(ACCOUNTS, payload=accounts_payload)
        async with aiohttp.ClientSession() as session:
            accounts = await fetch_accounts(session, ACCESS_URL, now)
        ((key, calls),) = m.requests.items()
        assert "fakepass" not in str(key[1])
        assert key[1].query["start-date"] == str(int(now.timestamp()))
        assert isinstance(calls[0].kwargs["auth"], aiohttp.BasicAuth)
    assert len(accounts) == 3


@pytest.mark.parametrize(("status", "match"), [(403, "403"), (500, "HTTP 500")])
async def test_fetch_errors_hide_credentials(status: int, match: str) -> None:
    with aioresponses() as m:
        m.get(ACCOUNTS, status=status)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SimpleFinError, match=match) as exc:
                await fetch_accounts(session, ACCESS_URL, ny(2026, 11, 16, 6, 0))
    assert "fakepass" not in str(exc.value)
    assert "fakeuser" not in str(exc.value)


async def test_network_error_is_wrapped() -> None:
    with aioresponses() as m:
        m.get(ACCOUNTS, exception=aiohttp.ClientConnectionError(ACCESS_URL))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(SimpleFinError) as exc:
                await fetch_accounts(session, ACCESS_URL, ny(2026, 11, 16, 6, 0))
    assert "fakepass" not in str(exc.value)


def test_next_fetch_time() -> None:
    times = [time(6), time(20)]
    assert next_fetch_time(ny(2026, 11, 16, 5, 0), times) == ny(2026, 11, 16, 6, 0)
    assert next_fetch_time(ny(2026, 11, 16, 6, 0), times) == ny(2026, 11, 16, 20, 0)
    assert next_fetch_time(ny(2026, 11, 16, 21, 0), times) == ny(2026, 11, 17, 6, 0)


def make_poller(
    tmp_path: Path, clock: FakeClock, session: aiohttp.ClientSession, cap: int = 4
) -> tuple[SimpleFinPoller, Store]:
    store = Store()
    poller = SimpleFinPoller(
        ACCESS_URL,
        [time(6), time(20)],
        store,
        QuotaGuard(tmp_path / "quota.json", cap, clock),
        HoldingsCache(tmp_path / "cache.json"),
        session,
        clock,
        sleep=no_sleep,
    )
    return poller, store


async def test_fresh_cache_means_no_startup_fetch(
    tmp_path: Path, accounts_payload: dict[str, Any]
) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    with aioresponses() as m:
        m.get(ACCOUNTS, payload=accounts_payload)
        async with aiohttp.ClientSession() as session:
            poller, _ = make_poller(tmp_path, clock, session)
            assert poller.load_cache()  # nothing cached yet
            assert await poller.fetch_once()

            # "Restart" two hours later with the cache on disk.
            clock.now += timedelta(hours=2)
            poller2, store2 = make_poller(tmp_path, clock, session)
            assert not poller2.load_cache()
            assert store2.accounts is not None and len(store2.accounts) == 3
        assert sum(len(c) for c in m.requests.values()) == 1


async def test_old_cache_triggers_startup_fetch(
    tmp_path: Path, accounts_payload: dict[str, Any]
) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    HoldingsCache(tmp_path / "cache.json").save(clock.now - timedelta(hours=25), [])
    async with aiohttp.ClientSession() as session:
        poller, _ = make_poller(tmp_path, clock, session)
        assert poller.load_cache()


async def test_quota_blocks_and_retries_stop(tmp_path: Path) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    with aioresponses() as m:
        m.get(ACCOUNTS, status=500, repeat=True)
        async with aiohttp.ClientSession() as session:
            poller, store = make_poller(tmp_path, clock, session, cap=2)
            await poller.fetch_with_retries()
            assert store.holdings_error is not None
            await poller.fetch_with_retries()
            assert store.holdings_error == "quota"
        assert sum(len(c) for c in m.requests.values()) == 2


async def test_successful_fetch_triggers_update(
    tmp_path: Path, accounts_payload: dict[str, Any]
) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    calls: list[bool] = []
    with aioresponses() as m:
        m.get(ACCOUNTS, payload=accounts_payload)
        async with aiohttp.ClientSession() as session:
            poller, store = make_poller(tmp_path, clock, session)
            poller.on_update = lambda: calls.append(True)
            await poller.fetch_with_retries()
    assert calls == [True]
    assert store.holdings_fetched_at == clock.now
    cached = (tmp_path / "cache.json").read_text()
    assert "balance" not in cached.replace("balance_date", "")


def test_redaction_of_access_url() -> None:
    register_secret(ACCESS_URL)
    record = logging.LogRecord(
        "x", logging.WARNING, __file__, 1, "failed for %s", (ACCESS_URL,), None
    )
    RedactingFilter().filter(record)
    assert "fakepass" not in record.getMessage()
    other = logging.LogRecord(
        "x", logging.WARNING, __file__, 1, "see https://u:p@other.invalid/x", None, None
    )
    RedactingFilter().filter(other)
    assert other.getMessage() == "see https://***@other.invalid/x"
