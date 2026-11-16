# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP API and static page (spec §8)."""

from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from aiohttp import web

from .dashboard import Dashboard

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

RATE_LIMIT = 120
RATE_WINDOW = 60.0
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'"
)

DASHBOARD_KEY = web.AppKey("dashboard", Dashboard)


class TokenAuth:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = [t.encode() for t in tokens]

    def check(self, header: str | None) -> bool:
        presented = b""
        if header and header[:7].lower() == "bearer ":
            presented = header[7:].strip().encode()
        # Compare against every token so timing doesn't reveal which one matched.
        ok = False
        for token in self._tokens:
            ok |= hmac.compare_digest(presented, token)
        return ok and bool(presented)


class RateLimiter:
    def __init__(
        self,
        limit: int = RATE_LIMIT,
        window: float = RATE_WINDOW,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.monotonic = monotonic
        self._hits: deque[float] = deque()

    def allow(self) -> bool:
        now = self.monotonic()
        while self._hits and self._hits[0] <= now - self.window:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            return False
        self._hits.append(now)
        return True


@web.middleware
async def security_headers(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        resp = exc
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if isinstance(resp, web.HTTPException):
        raise resp
    return resp


def create_app(
    dashboard: Dashboard,
    tokens: list[str],
    web_dir: Path,
    clock: Callable[[], datetime],
    limiter: RateLimiter | None = None,
) -> web.Application:
    auth = TokenAuth(tokens)
    limiter = limiter or RateLimiter()
    app = web.Application(middlewares=[security_headers])
    app[DASHBOARD_KEY] = dashboard

    async def get_dashboard(request: web.Request) -> web.Response:
        if not limiter.allow():
            return web.json_response(
                {"error": "rate_limited"}, status=429, headers={"Retry-After": "30"}
            )
        if not auth.check(request.headers.get("Authorization")):
            return web.json_response(
                {"error": "unauthorized"}, status=401, headers={"WWW-Authenticate": "Bearer"}
            )
        return web.json_response(dashboard.body(clock()), headers={"Cache-Control": "no-store"})

    async def healthz(request: web.Request) -> web.Response:
        return web.json_response(dashboard.health(clock()), headers={"Cache-Control": "no-store"})

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-cache"})

    app.router.add_get("/v1/dashboard", get_dashboard)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)
    app.router.add_static("/assets/", web_dir / "assets")
    return app
