"""
Centralised logging + optional Sentry setup.

Import once from app.py / bot.py and call init_logging(). Other modules just do:

    import logging
    logger = logging.getLogger(__name__)
    logger.info("...")

Exception logging:
    try: ...
    except Exception:
        logger.exception("failed to ...")  # includes traceback automatically

Environment variables:
    LOG_LEVEL          INFO/DEBUG/WARNING/ERROR (default INFO)
    LOG_FORMAT         "plain" (default) or "json"
    SENTRY_DSN         If set, errors are sent to Sentry too
    SENTRY_ENV         e.g. "production" / "staging" (default: "production")
    SENTRY_TRACES_RATE Float 0..1 — APM tracing sample rate (default 0)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Optional


# ── Request-id filter ──────────────────────────────────────────────────
# Pulls request_id from flask.g if running inside a request, otherwise
# returns "-". Enables tracing a single request across all log lines.

class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rid = "-"
        try:
            from flask import g, has_request_context
            if has_request_context() and hasattr(g, "request_id"):
                rid = g.request_id
        except Exception:
            pass
        record.request_id = rid
        return True


# ── Formatters ─────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """One JSON object per line — easy to ingest into Datadog/Loki/etc."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_PLAIN_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | rid=%(request_id)s | %(message)s"
)


# ── Public init ────────────────────────────────────────────────────────

_initialised = False


def init_logging(*, force: bool = False) -> logging.Logger:
    """Configure the root logger. Idempotent. Returns the root logger."""
    global _initialised
    if _initialised and not force:
        return logging.getLogger()

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = (os.getenv("LOG_FORMAT") or "plain").lower()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_PLAIN_FORMAT, "%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    # Replace any existing handlers (e.g. Flask's default) to avoid duplicate lines.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    # Tone down a few extremely chatty 3rd-party loggers
    for noisy in ("werkzeug", "urllib3", "telegram", "httpx", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _init_sentry()

    _initialised = True
    return root


# ── Sentry (optional) ──────────────────────────────────────────────────

def _init_sentry() -> None:
    """Initialise Sentry only if SENTRY_DSN is set. Safe to call without
    sentry_sdk installed — we fail soft."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; skipping Sentry init"
        )
        return

    try:
        traces_rate = float(os.getenv("SENTRY_TRACES_RATE", "0") or "0")
    except ValueError:
        traces_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENV", "production"),
        traces_sample_rate=traces_rate,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        send_default_pii=False,  # no Telegram user content in error reports
    )
    logging.getLogger(__name__).info("Sentry initialised (env=%s)",
                                     os.getenv("SENTRY_ENV", "production"))


# ── Flask request-id middleware ────────────────────────────────────────

def install_request_id_middleware(flask_app) -> None:
    """Attach a request_id (UUID4) to flask.g for every request.

    The configured logging filter pulls it into log records automatically.
    Also exposes it as the X-Request-Id response header so clients / logs
    can correlate.
    """
    from flask import g, request

    @flask_app.before_request
    def _set_request_id():
        # Honour an inbound X-Request-Id (e.g. from a load balancer)
        incoming = (request.headers.get("X-Request-Id") or "").strip()
        g.request_id = incoming or uuid.uuid4().hex[:16]

    @flask_app.after_request
    def _expose_request_id(response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers["X-Request-Id"] = rid
        return response
