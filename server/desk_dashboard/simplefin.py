# SPDX-License-Identifier: GPL-3.0-or-later
"""SimpleFIN Bridge client, holdings cache and schedule (spec §4.1)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from pathlib import Path

import aiohttp
from yarl import URL

from . import market
from .holdings import Account, parse_accounts
from .persist import read_json, write_json
from .quota import QuotaGuard
from .store import Store

log = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=60, connect=15)
RETRY_DELAYS = (300, 1800)  # seconds; each retry also needs quota
CACHE_MAX_AGE = timedelta(hours=24)


class SimpleFinError(Exception):
    """Carries only a safe message: never the URL or credentials."""


def split_access_url(access_url: str) -> tuple[URL, aiohttp.BasicAuth | None]:
    url = URL(access_url)
    auth = None
    if url.user is not None:
        auth = aiohttp.BasicAuth(url.user, url.password or "")
    return url.with_user(None).with_password(None), auth


async def fetch_accounts(
    session: aiohttp.ClientSession, access_url: str, now: datetime
) -> list[Account]:
    base, auth = split_access_url(access_url)
    url = base.with_path(base.path.rstrip("/") + "/accounts")
    # Smallest transaction window: we only want balances and holdings.
    params = {"start-date": str(int(now.timestamp()))}
    try:
        async with session.get(url, params=params, auth=auth, timeout=TIMEOUT) as resp:
            if resp.status == 403:
                raise SimpleFinError("access denied (403): the Access URL may be revoked")
            if resp.status != 200:
                raise SimpleFinError(f"HTTP {resp.status}")
            payload = await resp.json(content_type=None)
    except aiohttp.ClientError as exc:
        raise SimpleFinError(f"network error: {type(exc).__name__}") from None
    except TimeoutError:
        raise SimpleFinError("timed out") from None
    try:
        accounts = parse_accounts(payload)
    except ValueError as exc:
        raise SimpleFinError(str(exc)) from None
    if isinstance(payload, dict) and payload.get("errors"):
        log.warning("SimpleFIN reported %d message(s) for this fetch", len(payload["errors"]))
    return accounts


class HoldingsCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[datetime, list[Account]] | None:
        if not self.path.exists():
            return None
        try:
            raw = read_json(self.path)
            fetched = datetime.fromisoformat(raw["fetched_at"])
            return fetched, [Account.from_json(a) for a in raw["accounts"]]
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("holdings cache unreadable; ignoring it")
            return None

    def save(self, fetched_at: datetime, accounts: list[Account]) -> None:
        write_json(
            self.path,
            {"fetched_at": fetched_at.isoformat(), "accounts": [a.to_json() for a in accounts]},
        )


def next_fetch_time(now: datetime, times: list[time]) -> datetime:
    local = now.astimezone(market.NY)
    for day_offset in range(3):
        day = local.date() + timedelta(days=day_offset)
        for t in times:
            candidate = datetime.combine(day, t, market.NY)
            if candidate > local:
                return candidate
    raise AssertionError("unreachable: fetch times is never empty")


class SimpleFinPoller:
    def __init__(
        self,
        access_url: str,
        fetch_times: list[time],
        store: Store,
        quota: QuotaGuard,
        cache: HoldingsCache,
        session: aiohttp.ClientSession,
        clock: Callable[[], datetime],
        on_update: Callable[[], None] = lambda: None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.access_url = access_url
        self.fetch_times = fetch_times
        self.store = store
        self.quota = quota
        self.cache = cache
        self.session = session
        self.clock = clock
        self.on_update = on_update
        self.sleep = sleep

    def load_cache(self) -> bool:
        """Load cached holdings. Returns True if a startup fetch is needed."""
        cached = self.cache.load()
        if cached is None:
            return True
        fetched_at, accounts = cached
        self.store.set_holdings(accounts, fetched_at)
        return self.clock() - fetched_at > CACHE_MAX_AGE

    async def fetch_once(self) -> bool:
        if not self.quota.try_acquire():
            log.warning(
                "SimpleFIN daily cap (%d per 24 h) reached; skipping fetch",
                self.quota.max_per_day,
            )
            self.store.holdings_error = "quota"
            return False
        now = self.clock()
        try:
            accounts = await fetch_accounts(self.session, self.access_url, now)
        except SimpleFinError as exc:
            log.warning("SimpleFIN fetch failed: %s", exc)
            self.store.holdings_error = str(exc)
            return False
        self.cache.save(now, accounts)
        self.store.set_holdings(accounts, now)
        with_holdings = sum(1 for a in accounts if a.holdings is not None)
        log.info(
            "SimpleFIN fetch ok: %d account(s), %d with holdings; %d request(s) left today",
            len(accounts),
            with_holdings,
            self.quota.remaining(),
        )
        self.on_update()
        return True

    async def fetch_with_retries(self) -> None:
        if await self.fetch_once():
            return
        for delay in RETRY_DELAYS:
            if self.quota.remaining() <= 0:
                return
            await self.sleep(delay)
            if await self.fetch_once():
                return

    async def run(self) -> None:
        if self.load_cache():
            await self.fetch_with_retries()
        else:
            log.info("holdings cache is fresh; no SimpleFIN fetch at startup")
        while True:
            target = next_fetch_time(self.clock(), self.fetch_times)
            await self.sleep(max(0.0, (target - self.clock()).total_seconds()))
            await self.fetch_with_retries()
