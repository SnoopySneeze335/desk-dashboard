# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory state shared by the pollers and the HTTP handlers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .holdings import Account
from .quote import Quote


@dataclass
class Store:
    accounts: list[Account] | None = None
    holdings_fetched_at: datetime | None = None
    holdings_error: str | None = None
    warned_unmapped: set[str] = field(default_factory=set)

    quotes: dict[str, Quote | None] = field(default_factory=dict)
    quotes_polled_at: datetime | None = None
    quotes_error: str | None = None

    cpu_samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    ram_pct: float | None = None
    metrics_at: datetime | None = None
    metrics_error: str | None = None

    def set_holdings(self, accounts: list[Account], fetched_at: datetime) -> None:
        self.accounts = accounts
        self.holdings_fetched_at = fetched_at
        self.holdings_error = None
        self.warned_unmapped = set()  # warn about unmapped symbols once per fetch

    def update_quotes(self, results: dict[str, Quote | None], polled_at: datetime) -> None:
        self.quotes.update(results)
        self.quotes_polled_at = polled_at
        self.quotes_error = None

    def add_metrics(self, cpu: float | None, ram: float, at: datetime, window_seconds: int) -> None:
        if cpu is not None:
            self.cpu_samples.append((at, cpu))
        cutoff = at - timedelta(seconds=window_seconds)
        while self.cpu_samples and self.cpu_samples[0][0] <= cutoff:
            self.cpu_samples.popleft()
        self.ram_pct = ram
        self.metrics_at = at
        self.metrics_error = None

    def cpu_smoothed(self) -> float | None:
        if not self.cpu_samples:
            return None
        return sum(v for _, v in self.cpu_samples) / len(self.cpu_samples)
