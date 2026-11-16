# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from desk_dashboard.market import NY

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NY)  # type: ignore[misc]


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def accounts_payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "simplefin_accounts.json").read_text())
    return data
