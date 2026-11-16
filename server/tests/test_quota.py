# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import timedelta
from pathlib import Path

from desk_dashboard.quota import QuotaGuard
from tests.conftest import FakeClock, ny


def test_cap_survives_restart(tmp_path: Path) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    path = tmp_path / "quota.json"
    guard = QuotaGuard(path, 2, clock)
    assert guard.try_acquire()
    assert guard.try_acquire()
    assert not guard.try_acquire()

    restarted = QuotaGuard(path, 2, clock)
    assert restarted.remaining() == 0
    assert not restarted.try_acquire()


def test_rolling_window(tmp_path: Path) -> None:
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    guard = QuotaGuard(tmp_path / "q.json", 1, clock)
    assert guard.try_acquire()
    clock.now += timedelta(hours=23, minutes=59)
    assert not guard.try_acquire()
    clock.now += timedelta(minutes=2)
    assert guard.try_acquire()


def test_corrupt_file_blocks_fetches(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text("{not json")
    clock = FakeClock(ny(2026, 11, 16, 6, 0))
    guard = QuotaGuard(path, 4, clock)
    assert not guard.try_acquire()
    clock.now += timedelta(hours=24, seconds=1)
    assert guard.try_acquire()
