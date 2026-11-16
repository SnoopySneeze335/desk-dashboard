# SPDX-License-Identifier: GPL-3.0-or-later
# Multi-stage build: dependencies are installed into a venv in the builder,
# then only the venv and app files are copied into a small Alpine runtime image.

ARG PYTHON_IMAGE=python:3.13.5-alpine3.22

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY server/requirements.txt /tmp/requirements.txt
RUN python -m venv /venv \
 && /venv/bin/pip install --require-virtualenv -r /tmp/requirements.txt

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="desk-dashboard" \
      org.opencontainers.image.description="Self-hosted at-a-glance portfolio and server dashboard" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PATH=/venv/bin:$PATH \
    PYTHONPATH=/app/server \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8080

RUN addgroup -S -g 10001 dashboard \
 && adduser -S -D -H -u 10001 -G dashboard -s /sbin/nologin dashboard \
 && mkdir -p /data && chown dashboard:dashboard /data

COPY --from=builder /venv /venv
COPY server/desk_dashboard /app/server/desk_dashboard
COPY config /app/config
COPY web /app/web

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz', timeout=4)"]

ENTRYPOINT ["python", "-m", "desk_dashboard"]
