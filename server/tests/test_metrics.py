# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import timedelta
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from desk_dashboard.metrics import HostSource, MetricsError, MetricsPoller, UnraidSource
from desk_dashboard.store import Store
from tests.conftest import FakeClock, ny

URL = "http://192.168.1.10/graphql"


async def test_unraid_parses_and_sends_key() -> None:
    with aioresponses() as m:
        m.post(
            URL,
            payload={
                "data": {
                    "metrics": {"cpu": {"percentTotal": 33.0}, "memory": {"percentTotal": 58.1}}
                }
            },
        )
        async with aiohttp.ClientSession() as session:
            cpu, ram = await UnraidSource(session, URL, "fake-key").sample()
        ((_, calls),) = m.requests.items()
        assert calls[0].kwargs["headers"] == {"x-api-key": "fake-key"}
        assert "percentTotal" in calls[0].kwargs["json"]["query"]
    assert (cpu, ram) == (33.0, 58.1)


@pytest.mark.parametrize(
    "payload",
    [
        {"errors": [{"message": "Forbidden"}]},
        {"data": {"metrics": None}},
        {"data": {"metrics": {"cpu": {"percentTotal": None}, "memory": {"percentTotal": 1}}}},
    ],
)
async def test_unraid_bad_payloads(payload: dict[str, object]) -> None:
    with aioresponses() as m:
        m.post(URL, payload=payload)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(MetricsError):
                await UnraidSource(session, URL, "k").sample()


async def test_host_source(tmp_path: Path) -> None:
    (tmp_path / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 400 kB\n")
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1\n")
    source = HostSource(tmp_path)
    cpu, ram = await source.sample()
    assert cpu is None
    assert ram == 60.0
    stat.write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")
    cpu, _ = await source.sample()
    assert cpu == 50.0


def test_cpu_smoothing_window() -> None:
    store = Store()
    t0 = ny(2026, 11, 16, 12, 0)
    for i, cpu in enumerate([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]):
        store.add_metrics(cpu, 50.0, t0 + timedelta(seconds=5 * i), 30)
    # window (t-30 s, t]: samples at 5..30 s -> 20..70
    assert store.cpu_smoothed() == pytest.approx(45.0)
    store.add_metrics(None, 51.0, t0 + timedelta(seconds=35), 30)
    assert store.ram_pct == 51.0


class Failing:
    async def sample(self) -> tuple[float | None, float]:
        raise MetricsError("boom")


async def test_backoff_on_failure() -> None:
    store = Store()
    poller = MetricsPoller(Failing(), 5, 30, store, FakeClock(ny(2026, 11, 16, 12, 0)))
    assert poller.delay() == 5
    await poller.poll()
    assert poller.delay() == 10
    for _ in range(10):
        await poller.poll()
    assert poller.delay() == 60
    assert store.metrics_error == "boom"
