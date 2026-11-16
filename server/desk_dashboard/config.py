# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration from environment variables (spec §9)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from .logsetup import register_secret

DEFAULT_CASH_SYMBOLS = (
    # Money-market and sweep tickers. Plain words like CASH or USD are left out
    # because they are also real stock tickers.
    "SPAXX,FDRXX,FZFXX,SPRXX,FCASH,CORE,VMFXX,VMRXX,VUSXX,SWVXX,SNVXX,SNSXX,SNOXX,SWTXX,QACDS,MMDA1"
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


def _read(env: Mapping[str, str], name: str, secret: bool = False) -> str | None:
    """Read NAME, or the contents of the file named by NAME_FILE."""
    value = env.get(name)
    file_path = env.get(f"{name}_FILE")
    if (value is None or value == "") and file_path:
        try:
            value = Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {name}_FILE: {exc.strerror}") from None
    if value is not None:
        value = value.strip()
    if not value:
        return None
    if secret:
        register_secret(value)
    return value


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 1) -> int:
    raw = _read(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = _read(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false")


def _csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _times(raw: str) -> list[time]:
    result = []
    for part in _csv(raw):
        try:
            hour, minute = part.split(":")
            result.append(time(int(hour), int(minute)))
        except ValueError:
            raise ConfigError(f"bad time {part!r} in SIMPLEFIN_FETCH_TIMES (use HH:MM)") from None
    if not result:
        raise ConfigError("SIMPLEFIN_FETCH_TIMES is empty")
    return sorted(result)


@dataclass(frozen=True)
class Config:
    dashboard_tokens: list[str]
    simplefin_access_url: str | None = None
    simplefin_accounts: list[str] = field(default_factory=list)
    simplefin_fetch_times: list[time] = field(default_factory=lambda: [time(6), time(20)])
    simplefin_max_requests_per_day: int = 4
    finnhub_api_key: str | None = None
    quote_interval_seconds: int = 60
    fund_proxies_file: Path | None = None
    default_fund_proxies_file: Path = REPO_ROOT / "config" / "fund-proxies.yaml"
    cash_symbols: frozenset[str] = frozenset(_csv(DEFAULT_CASH_SYMBOLS))
    server_metrics_source: str = "host"
    unraid_graphql_url: str | None = None
    unraid_api_key: str | None = None
    metrics_interval_seconds: int = 5
    cpu_smoothing_seconds: int = 30
    server_display_name: str = "Server"
    hide_dollar_amounts: bool = False
    demo_mode: bool = False
    data_dir: Path = Path("/data")
    web_dir: Path = REPO_ROOT / "web"
    port: int = 8080
    log_level: str = "info"


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    demo = _bool(env, "DEMO_MODE")
    tokens = _csv(_read(env, "DASHBOARD_TOKENS", secret=True))
    for token in tokens:
        register_secret(token)
    if not tokens:
        if not demo:
            raise ConfigError("DASHBOARD_TOKENS is required")
        tokens = ["demo"]

    unraid_url = _read(env, "UNRAID_GRAPHQL_URL", secret=False)
    source = (_read(env, "SERVER_METRICS_SOURCE") or ("unraid" if unraid_url else "host")).lower()
    if source not in ("unraid", "host", "off"):
        raise ConfigError("SERVER_METRICS_SOURCE must be unraid, host or off")
    if source == "unraid" and not unraid_url:
        raise ConfigError("SERVER_METRICS_SOURCE=unraid needs UNRAID_GRAPHQL_URL")

    proxies_file = _read(env, "FUND_PROXIES_FILE")
    cash = _read(env, "CASH_SYMBOLS")
    level = (_read(env, "LOG_LEVEL") or "info").lower()
    if level not in ("debug", "info", "warning", "error"):
        raise ConfigError("LOG_LEVEL must be debug, info, warning or error")

    kwargs: dict[str, object] = {}
    if default_map := _read(env, "DEFAULT_FUND_PROXIES_FILE"):
        kwargs["default_fund_proxies_file"] = Path(default_map)
    if web_dir := _read(env, "WEB_DIR"):
        kwargs["web_dir"] = Path(web_dir)

    return Config(
        dashboard_tokens=tokens,
        simplefin_access_url=_read(env, "SIMPLEFIN_ACCESS_URL", secret=True),
        simplefin_accounts=_csv(_read(env, "SIMPLEFIN_ACCOUNTS")),
        simplefin_fetch_times=_times(_read(env, "SIMPLEFIN_FETCH_TIMES") or "06:00,20:00"),
        simplefin_max_requests_per_day=_int(env, "SIMPLEFIN_MAX_REQUESTS_PER_DAY", 4),
        finnhub_api_key=_read(env, "FINNHUB_API_KEY", secret=True),
        quote_interval_seconds=_int(env, "QUOTE_INTERVAL_SECONDS", 60, minimum=10),
        fund_proxies_file=Path(proxies_file) if proxies_file else None,
        cash_symbols=frozenset(s.upper() for s in _csv(cash or DEFAULT_CASH_SYMBOLS)),
        server_metrics_source=source,
        unraid_graphql_url=unraid_url,
        unraid_api_key=_read(env, "UNRAID_API_KEY", secret=True),
        metrics_interval_seconds=_int(env, "METRICS_INTERVAL_SECONDS", 5),
        cpu_smoothing_seconds=_int(env, "CPU_SMOOTHING_SECONDS", 30),
        server_display_name=_read(env, "SERVER_DISPLAY_NAME") or "Server",
        hide_dollar_amounts=_bool(env, "HIDE_DOLLAR_AMOUNTS"),
        demo_mode=demo,
        data_dir=Path(_read(env, "DATA_DIR") or "/data"),
        port=_int(env, "PORT", 8080),
        log_level=level,
        **kwargs,  # type: ignore[arg-type]
    )
