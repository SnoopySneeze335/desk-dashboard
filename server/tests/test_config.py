# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import time
from pathlib import Path

import pytest

from desk_dashboard.config import ConfigError, load_config
from desk_dashboard.logsetup import redact


def test_tokens_required() -> None:
    with pytest.raises(ConfigError, match="DASHBOARD_TOKENS"):
        load_config({})


def test_demo_defaults_token() -> None:
    cfg = load_config({"DEMO_MODE": "true"})
    assert cfg.dashboard_tokens == ["demo"]


def test_defaults() -> None:
    cfg = load_config({"DASHBOARD_TOKENS": "aaaa1111, bbbb2222"})
    assert cfg.dashboard_tokens == ["aaaa1111", "bbbb2222"]
    assert cfg.simplefin_fetch_times == [time(6), time(20)]
    assert cfg.simplefin_max_requests_per_day == 4
    assert cfg.quote_interval_seconds == 60
    assert cfg.server_metrics_source == "host"
    assert cfg.hide_dollar_amounts is False
    assert cfg.port == 8080
    assert "SWVXX" in cfg.cash_symbols


def test_unraid_source_defaults_when_url_set() -> None:
    cfg = load_config(
        {"DASHBOARD_TOKENS": "t1234", "UNRAID_GRAPHQL_URL": "http://192.168.1.10/graphql"}
    )
    assert cfg.server_metrics_source == "unraid"


def test_secret_from_file_is_redacted(tmp_path: Path) -> None:
    secret_file = tmp_path / "finnhub"
    secret_file.write_text("file-secret-value\n")
    cfg = load_config({"DASHBOARD_TOKENS": "t1234", "FINNHUB_API_KEY_FILE": str(secret_file)})
    assert cfg.finnhub_api_key == "file-secret-value"
    assert redact("key=file-secret-value") == "key=***"


@pytest.mark.parametrize(
    "env",
    [
        {"SIMPLEFIN_FETCH_TIMES": "6am"},
        {"SERVER_METRICS_SOURCE": "snmp"},
        {"SERVER_METRICS_SOURCE": "unraid"},
        {"HIDE_DOLLAR_AMOUNTS": "maybe"},
        {"QUOTE_INTERVAL_SECONDS": "1"},
    ],
)
def test_bad_values(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_config({"DASHBOARD_TOKENS": "t1234", **env})


def test_default_proxy_map_loads() -> None:
    from desk_dashboard.proxies import load_proxy_map

    cfg = load_config({"DASHBOARD_TOKENS": "t1234"})
    proxies = load_proxy_map(cfg.default_fund_proxies_file)
    assert proxies["VFIAX"].symbol == "VOO"
    assert proxies["VEMAX"].symbol == "VWO"
    assert not any(p.approximate for p in proxies.values())


def test_user_proxy_map_merges(tmp_path: Path) -> None:
    from desk_dashboard.proxies import load_proxy_map

    cfg = load_config({"DASHBOARD_TOKENS": "t1234"})
    user = tmp_path / "proxies.yaml"
    user.write_text("VFIAX: SPY\nSOMEFUND: { proxy: VOO, approximate: true }\n")
    proxies = load_proxy_map(cfg.default_fund_proxies_file, user)
    assert proxies["VFIAX"].symbol == "SPY"
    assert proxies["SOMEFUND"].approximate
