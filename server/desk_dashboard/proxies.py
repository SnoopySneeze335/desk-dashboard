# SPDX-License-Identifier: GPL-3.0-or-later
"""Fund → ETF proxy map (spec §6)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Proxy:
    symbol: str
    approximate: bool = False


class ProxyMapError(ValueError):
    pass


def _parse(data: Any, source: str) -> dict[str, Proxy]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProxyMapError(f"{source}: expected a mapping of FUND: ETF")
    result: dict[str, Proxy] = {}
    for fund, entry in data.items():
        key = str(fund).strip().upper()
        if isinstance(entry, str):
            result[key] = Proxy(entry.strip().upper())
        elif isinstance(entry, dict) and isinstance(entry.get("proxy"), str):
            result[key] = Proxy(entry["proxy"].strip().upper(), bool(entry.get("approximate")))
        else:
            raise ProxyMapError(f"{source}: bad entry for {key}")
    return result


def load_proxy_map(default_file: Path, user_file: Path | None = None) -> dict[str, Proxy]:
    with default_file.open(encoding="utf-8") as fh:
        merged = _parse(yaml.safe_load(fh), default_file.name)
    if user_file is not None:
        with user_file.open(encoding="utf-8") as fh:
            merged.update(_parse(yaml.safe_load(fh), user_file.name))
    approx = sorted(f for f, p in merged.items() if p.approximate)
    if approx:
        log.info("approximate fund proxies in use: %s", ", ".join(approx))
    return merged
