# SPDX-License-Identifier: GPL-3.0-or-later
"""Server CPU/RAM from Unraid GraphQL or host /proc (spec §4.3)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import aiohttp

from .store import Store

log = logging.getLogger(__name__)
QUERY = "{ metrics { cpu { percentTotal } memory { percentTotal } } }"
MAX_BACKOFF = 60.0


class MetricsError(Exception):
    pass


class Source(Protocol):
    async def sample(self) -> tuple[float | None, float]: ...


def _pct(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MetricsError("missing percentTotal")
    return max(0.0, min(100.0, float(value)))


class UnraidSource:
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str | None) -> None:
        self.session = session
        self.url = url
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.timeout = aiohttp.ClientTimeout(total=4)

    async def sample(self) -> tuple[float | None, float]:
        try:
            async with self.session.post(
                self.url, json={"query": QUERY}, headers=self.headers, timeout=self.timeout
            ) as resp:
                if resp.status != 200:
                    raise MetricsError(f"HTTP {resp.status}")
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise MetricsError(f"network error: {type(exc).__name__}") from None
        except TimeoutError:
            raise MetricsError("timed out") from None
        try:
            m = payload["data"]["metrics"]
            return _pct(m["cpu"]["percentTotal"]), _pct(m["memory"]["percentTotal"])
        except (KeyError, TypeError):
            if isinstance(payload, dict) and payload.get("errors"):
                raise MetricsError("GraphQL error (check the API key's role)") from None
            raise MetricsError("unexpected response shape") from None


class HostSource:
    """Host-wide numbers: /proc/stat and /proc/meminfo aren't namespaced."""

    def __init__(self, proc: Path = Path("/proc")) -> None:
        self.proc = proc
        self._last: tuple[int, int] | None = None

    def _cpu_times(self) -> tuple[int, int]:
        first = (self.proc / "stat").read_text().splitlines()[0].split()
        values = [int(v) for v in first[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
        return sum(values[:8]), idle

    def _ram(self) -> float:
        info: dict[str, int] = {}
        for line in (self.proc / "meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0])
        total = info["MemTotal"]
        available = info.get("MemAvailable", info.get("MemFree", 0))
        return _pct(100.0 * (total - available) / total)

    async def sample(self) -> tuple[float | None, float]:
        try:
            total, idle = self._cpu_times()
            ram = self._ram()
        except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError) as exc:
            raise MetricsError(f"cannot read /proc: {type(exc).__name__}") from None
        cpu = None
        if self._last is not None:
            d_total = total - self._last[0]
            d_idle = idle - self._last[1]
            if d_total > 0:
                cpu = _pct(100.0 * (d_total - d_idle) / d_total)
        self._last = (total, idle)
        return cpu, ram


class MetricsPoller:
    def __init__(
        self,
        source: Source,
        interval: int,
        window: int,
        store: Store,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.source = source
        self.interval = interval
        self.window = window
        self.store = store
        self.clock = clock
        self.sleep = sleep
        self.failures = 0

    async def poll(self) -> None:
        try:
            cpu, ram = await self.source.sample()
        except MetricsError as exc:
            self.failures += 1
            if self.failures in (1, 10) or self.failures % 100 == 0:
                log.warning("server metrics failed (%d in a row): %s", self.failures, exc)
            self.store.metrics_error = str(exc)
            return
        if self.failures:
            log.info("server metrics recovered")
        self.failures = 0
        self.store.add_metrics(cpu, ram, self.clock(), self.window)

    def delay(self) -> float:
        if not self.failures:
            return float(self.interval)
        return min(MAX_BACKOFF, self.interval * 2.0 ** min(self.failures, 6))

    async def run(self) -> None:
        while True:
            await self.poll()
            await self.sleep(self.delay())
