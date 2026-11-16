# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: python -m desk_dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from datetime import datetime
from typing import Any

import aiohttp
from aiohttp import web

from . import __version__, market
from .app import create_app
from .config import Config, ConfigError, load_config
from .dashboard import Dashboard
from .demo import DEMO_PROXIES, run_demo
from .finnhub import QuotePoller
from .logsetup import setup_logging
from .metrics import HostSource, MetricsPoller, Source, UnraidSource
from .proxies import load_proxy_map
from .quota import QuotaGuard
from .simplefin import HoldingsCache, SimpleFinPoller
from .store import Store

log = logging.getLogger("desk_dashboard")


def utcnow() -> datetime:
    return datetime.now(market.UTC)


async def serve(cfg: Config) -> None:
    store = Store()
    proxy_map = (
        dict(DEMO_PROXIES)
        if cfg.demo_mode
        else load_proxy_map(cfg.default_fund_proxies_file, cfg.fund_proxies_file)
    )
    dashboard = Dashboard(cfg, store, proxy_map)
    app = create_app(dashboard, cfg.dashboard_tokens, cfg.web_dir, utcnow)

    tasks: list[asyncio.Task[None]] = []
    session = aiohttp.ClientSession(headers={"User-Agent": f"desk-dashboard/{__version__}"})

    def spawn(name: str, factory: Any) -> None:
        async def supervise() -> None:
            delay = 5.0
            while True:
                try:
                    await factory()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s poller crashed; restarting in %.0f s", name, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

        tasks.append(asyncio.create_task(supervise(), name=name))

    if cfg.demo_mode:
        log.warning("DEMO_MODE is on: serving synthetic data, no upstream calls")
        if cfg.dashboard_tokens == ["demo"]:
            log.warning("no DASHBOARD_TOKENS set; demo token is 'demo'")
        spawn("demo", lambda: run_demo(store, utcnow, cfg.cpu_smoothing_seconds))
    else:
        quotes: QuotePoller | None = None
        if cfg.finnhub_api_key:
            quotes = QuotePoller(
                cfg.finnhub_api_key,
                cfg.quote_interval_seconds,
                store,
                dashboard.quote_symbols,
                session,
                utcnow,
            )
        if cfg.simplefin_access_url:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            poller = SimpleFinPoller(
                cfg.simplefin_access_url,
                cfg.simplefin_fetch_times,
                store,
                QuotaGuard(
                    cfg.data_dir / "simplefin-quota.json",
                    cfg.simplefin_max_requests_per_day,
                    utcnow,
                ),
                HoldingsCache(cfg.data_dir / "holdings-cache.json"),
                session,
                utcnow,
                on_update=(quotes.trigger.set if quotes else lambda: None),
            )
            spawn("simplefin", poller.run)
        else:
            log.info("SIMPLEFIN_ACCESS_URL not set; portfolio is unconfigured")
        if quotes is not None:
            spawn("finnhub", quotes.run)
        else:
            log.info("FINNHUB_API_KEY not set; positions other than cash stay pending")
        if cfg.server_metrics_source != "off":
            source: Source
            if cfg.server_metrics_source == "unraid":
                assert cfg.unraid_graphql_url is not None
                source = UnraidSource(session, cfg.unraid_graphql_url, cfg.unraid_api_key)
            else:
                source = HostSource()
            metrics = MetricsPoller(
                source, cfg.metrics_interval_seconds, cfg.cpu_smoothing_seconds, store, utcnow
            )
            spawn("metrics", metrics.run)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=cfg.port)  # noqa: S104 - container
    await site.start()
    log.info("desk-dashboard %s listening on port %d", __version__, cfg.port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.cleanup()
    await session.close()


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    setup_logging(cfg.log_level)
    asyncio.run(serve(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
