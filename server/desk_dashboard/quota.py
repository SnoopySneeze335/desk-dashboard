# SPDX-License-Identifier: GPL-3.0-or-later
"""Persisted SimpleFIN request cap over a rolling 24 hours (spec §4.1)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .persist import read_json, write_json

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=24)


class QuotaGuard:
    """Every attempt is recorded *before* the request goes out, so a crash
    mid-request still counts against the cap."""

    def __init__(self, path: Path, max_per_day: int, clock: Callable[[], datetime]) -> None:
        self.path = path
        self.max_per_day = max_per_day
        self.clock = clock
        self._stamps = self._load()

    def _load(self) -> list[datetime]:
        if not self.path.exists():
            return []
        try:
            raw = read_json(self.path)
            return [datetime.fromisoformat(s) for s in raw["requests"]]
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable state: assume the cap is used up rather than risk a block.
            log.error("SimpleFIN quota file unreadable; pausing fetches for 24 hours")
            return [self.clock()] * self.max_per_day

    def _prune(self) -> None:
        cutoff = self.clock() - WINDOW
        self._stamps = [s for s in self._stamps if s > cutoff]

    def used(self) -> int:
        self._prune()
        return len(self._stamps)

    def remaining(self) -> int:
        return max(0, self.max_per_day - self.used())

    def try_acquire(self) -> bool:
        if self.remaining() <= 0:
            return False
        self._stamps.append(self.clock())
        write_json(self.path, {"requests": [s.isoformat() for s in self._stamps]})
        return True
