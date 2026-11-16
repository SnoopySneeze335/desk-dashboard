# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging with secret redaction.

Secrets are registered once at startup; every log record is scrubbed of them
and of any URL userinfo, so a stray exception message can't leak credentials.
"""

from __future__ import annotations

import logging
import re

_URL_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 4:
        _secrets.add(value)


def redact(text: str) -> str:
    text = _URL_USERINFO.sub(r"\g<scheme>***@", text)
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message)
        record.args = None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # aiohttp's access log would record every screen poll; keep it quiet.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
