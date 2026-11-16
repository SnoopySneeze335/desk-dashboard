# SPDX-License-Identifier: GPL-3.0-or-later
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from desk_dashboard.app import RateLimiter, create_app
from desk_dashboard.config import Config
from desk_dashboard.dashboard import Dashboard
from desk_dashboard.holdings import parse_accounts
from desk_dashboard.proxies import Proxy
from desk_dashboard.quote import Quote
from desk_dashboard.store import Store
from tests.conftest import FakeClock, ny

TOKEN = "fake-token-1234"
NOW = ny(2026, 11, 16, 11, 0)
FORBIDDEN = [
    "ACT-0001",
    "Fake Brokerage",
    "VFIAX",
    'FAKE"',
    "SWVXX",
    "ZZZZX",
    "VOO",
    "25000",
    "12000",
    'holdings":[',
    'balance"',
]


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    (tmp_path / "assets" / "app.js").write_text("// js")
    return tmp_path


def base_config(**kw: Any) -> Config:
    cfg = Config(
        dashboard_tokens=[TOKEN, "second-fake-token"],
        simplefin_access_url="https://u:p@bridge.example.invalid/simplefin",
        finnhub_api_key="fake-key",
        cash_symbols=frozenset({"SWVXX"}),
        server_metrics_source="host",
    )
    return replace(cfg, **kw)


def loaded_store(accounts_payload: dict[str, Any]) -> Store:
    store = Store()
    store.set_holdings(parse_accounts(accounts_payload), NOW - timedelta(hours=5))
    store.update_quotes(
        {
            "FAKE": Quote(c=D("101.5"), d=D("1.50"), dp=D("1.5"), pc=D("100"), t=NOW),
            "VOO": Quote(c=D("505"), d=D("5"), dp=D("1.0"), pc=D("500"), t=NOW),
            "ZZZZX": None,
        },
        NOW - timedelta(seconds=30),
    )
    store.add_metrics(33.0, 58.1, NOW - timedelta(seconds=2), 30)
    return store


async def client_for(
    cfg: Config, store: Store, web_dir: Path, clock: FakeClock, limiter: RateLimiter | None = None
) -> TestClient:  # type: ignore[type-arg]
    dash = Dashboard(cfg, store, {"VFIAX": Proxy("VOO")})
    app = create_app(dash, cfg.dashboard_tokens, web_dir, clock, limiter)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def get(client: TestClient, token: str | None = TOKEN) -> Any:  # type: ignore[type-arg]
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return await client.get("/v1/dashboard", headers=headers)


async def test_auth(accounts_payload: dict[str, Any], web_dir: Path) -> None:
    client = await client_for(
        base_config(), loaded_store(accounts_payload), web_dir, FakeClock(NOW)
    )
    try:
        for token in (None, "wrong", "", TOKEN + "x"):
            resp = await get(client, token)
            assert resp.status == 401
            assert await resp.json() == {"error": "unauthorized"}
        resp = await client.get("/v1/dashboard", headers={"Authorization": f"Basic {TOKEN}"})
        assert resp.status == 401
        assert (await get(client)).status == 200
        assert (await get(client, "second-fake-token")).status == 200
    finally:
        await client.close()


async def test_body_values_and_no_forbidden_fields(
    accounts_payload: dict[str, Any], web_dir: Path
) -> None:
    client = await client_for(
        base_config(), loaded_store(accounts_payload), web_dir, FakeClock(NOW)
    )
    try:
        resp = await get(client)
        text = await resp.text()
        body = json.loads(text)
    finally:
        await client.close()
    assert resp.headers["Cache-Control"] == "no-store"
    p = body["portfolio"]
    assert p["status"] == "partial"
    assert p["day_change"] == 135.0
    assert p["day_change_pct"] == 1.0
    assert p["positions"] == {"total": 4, "priced": 3, "pending": 1}
    assert p["market"] == {"state": "open", "session_date": "2026-11-16", "label": "Live"}
    assert p["as_of"] == {"holdings": "2026-11-16T11:00:00Z", "quotes": "2026-11-16T16:00:00Z"}
    s = body["server"]
    assert s == {
        "status": "ok",
        "name": "Server",
        "cpu_pct": 33.0,
        "ram_pct": 58.1,
        "as_of": "2026-11-16T15:59:58Z",
    }
    assert body["generated_at"] == "2026-11-16T16:00:00Z"
    for needle in FORBIDDEN:
        assert needle not in text, needle
    assert set(body) == {"generated_at", "portfolio", "server"}
    assert set(p) == {"status", "market", "day_change", "day_change_pct", "positions", "as_of"}


async def test_hide_dollar_amounts(accounts_payload: dict[str, Any], web_dir: Path) -> None:
    client = await client_for(
        base_config(hide_dollar_amounts=True),
        loaded_store(accounts_payload),
        web_dir,
        FakeClock(NOW),
    )
    try:
        body = await (await get(client)).json()
    finally:
        await client.close()
    assert body["portfolio"]["day_change"] is None
    assert body["portfolio"]["day_change_pct"] == 1.0


async def test_unconfigured_sections(web_dir: Path) -> None:
    cfg = base_config(simplefin_access_url=None, finnhub_api_key=None, server_metrics_source="off")
    client = await client_for(cfg, Store(), web_dir, FakeClock(NOW))
    try:
        body = await (await get(client)).json()
        health = await (await client.get("/healthz")).json()
    finally:
        await client.close()
    assert body["portfolio"]["status"] == "unconfigured"
    assert body["portfolio"]["day_change"] is None
    assert body["server"]["status"] == "unconfigured"
    assert body["server"]["cpu_pct"] is None
    assert health == {
        "ok": True,
        "sources": {
            "simplefin": "unconfigured",
            "finnhub": "unconfigured",
            "server": "unconfigured",
        },
    }


def test_stale_thresholds(accounts_payload: dict[str, Any]) -> None:
    store = loaded_store(accounts_payload)
    dash = Dashboard(base_config(), store, {"VFIAX": Proxy("VOO")})

    # quotes: polled 30 s before NOW; stale after 5 min while open
    assert dash.quotes_state(NOW + timedelta(minutes=4)) == "ok"
    assert dash.quotes_state(NOW + timedelta(minutes=5, seconds=31)) == "stale"
    assert dash.portfolio(NOW + timedelta(minutes=6))["status"] == "stale"
    # ...but not once the market has closed
    assert dash.quotes_state(ny(2026, 11, 16, 19, 0)) == "ok"

    # holdings: fetched 5 h before NOW; stale after 36 h
    assert dash.holdings_state(NOW + timedelta(hours=30)) == "ok"
    assert dash.holdings_state(NOW + timedelta(hours=31, seconds=1)) == "stale"

    # server metrics: 2 s old at NOW; stale after 30 s
    assert dash.server_state(NOW + timedelta(seconds=27)) == "ok"
    assert dash.server_state(NOW + timedelta(seconds=29)) == "stale"
    assert dash.server(NOW + timedelta(seconds=29))["status"] == "stale"


def test_error_states() -> None:
    store = Store()
    dash = Dashboard(base_config(), store, {})
    assert dash.holdings_state(NOW) == "stale"  # first fetch not done yet
    store.holdings_error = "HTTP 500"
    assert dash.portfolio(NOW)["status"] == "error"
    store.metrics_error = "timed out"
    assert dash.server(NOW)["status"] == "error"


async def test_healthz_has_no_values(accounts_payload: dict[str, Any], web_dir: Path) -> None:
    client = await client_for(
        base_config(), loaded_store(accounts_payload), web_dir, FakeClock(NOW)
    )
    try:
        resp = await client.get("/healthz")
        body = await resp.json()
    finally:
        await client.close()
    assert resp.status == 200
    assert body == {"ok": True, "sources": {"simplefin": "ok", "finnhub": "ok", "server": "ok"}}


async def test_static_page_needs_no_auth(web_dir: Path) -> None:
    client = await client_for(base_config(), Store(), web_dir, FakeClock(NOW))
    try:
        resp = await client.get("/")
        assert resp.status == 200
        assert "Content-Security-Policy" in resp.headers
        assert (await client.get("/assets/app.js")).status == 200
        assert (await client.get("/assets/../index.html")).status in (403, 404)
    finally:
        await client.close()


async def test_rate_limit(web_dir: Path) -> None:
    ticks = [0.0]
    limiter = RateLimiter(limit=3, window=60, monotonic=lambda: ticks[0])
    client = await client_for(base_config(), Store(), web_dir, FakeClock(NOW), limiter)
    try:
        assert [(await get(client)).status for _ in range(4)] == [200, 200, 200, 429]
        ticks[0] = 61.0
        assert (await get(client)).status == 200
    finally:
        await client.close()


def test_unmapped_warning_once_per_fetch(
    accounts_payload: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    store = loaded_store(accounts_payload)
    dash = Dashboard(base_config(), store, {"VFIAX": Proxy("VOO")})
    dash.portfolio(NOW)
    dash.portfolio(NOW)
    assert sum("ZZZZX" in r.getMessage() for r in caplog.records) == 1
    store.set_holdings(store.accounts or [], NOW)
    dash.portfolio(NOW)
    assert sum("ZZZZX" in r.getMessage() for r in caplog.records) == 2
