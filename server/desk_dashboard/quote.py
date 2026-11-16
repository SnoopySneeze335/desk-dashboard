# SPDX-License-Identifier: GPL-3.0-or-later
"""Finnhub quote model (spec §4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .holdings import parse_decimal


@dataclass(frozen=True)
class Quote:
    c: Decimal
    d: Decimal
    dp: Decimal
    pc: Decimal
    t: datetime


def parse_quote(payload: Any) -> Quote | None:
    """Return None for anything unpriceable (c: 0, nulls, wrong shape)."""
    if not isinstance(payload, dict):
        return None
    c = parse_decimal(payload.get("c"))
    d = parse_decimal(payload.get("d"))
    dp = parse_decimal(payload.get("dp"))
    pc = parse_decimal(payload.get("pc"))
    t_raw = payload.get("t")
    if c is None or d is None or dp is None or pc is None or not isinstance(t_raw, int | float):
        return None
    if c <= 0 or pc <= 0 or t_raw <= 0:
        return None
    return Quote(c=c, d=d, dp=dp, pc=pc, t=datetime.fromtimestamp(t_raw, tz=UTC))
