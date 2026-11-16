# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import timedelta

from desk_dashboard.config import load_config
from desk_dashboard.dashboard import Dashboard
from desk_dashboard.demo import DEMO_PROXIES, demo_accounts, demo_quotes
from desk_dashboard.store import Store
from tests.conftest import ny


def test_demo_serves_valid_numbers_any_time() -> None:
    cfg = load_config({"DEMO_MODE": "1"})
    for now in (ny(2026, 11, 16, 11, 0), ny(2026, 11, 14, 12, 0), ny(2026, 11, 16, 7, 0)):
        store = Store()
        store.set_holdings(demo_accounts(now), now)
        store.update_quotes(demo_quotes(now), now)
        store.add_metrics(30.0, 58.0, now, 30)
        body = Dashboard(cfg, store, dict(DEMO_PROXIES)).body(now + timedelta(seconds=1))
        p = body["portfolio"]
        assert p["status"] == "partial"
        assert p["positions"] == {"total": 5, "priced": 4, "pending": 1}
        assert isinstance(p["day_change"], float)
        assert isinstance(p["day_change_pct"], float)
        assert body["server"]["status"] == "ok"
