"""
Webhook adapter for python-telegram-bot v20 inside a synchronous Flask app.

PTB v20 is async; Flask is sync. We run the bot's asyncio event loop in a
daemon thread, build the Application without an Updater (no polling), and
expose a synchronous `process_update_dict()` that Flask handlers can call.

Each Telegram update arriving on /telegram/webhook is JSON-decoded by Flask,
then submitted as a coroutine onto the bg loop and awaited (with timeout).

Usage (typically from app.py):

    from webhook import WebhookBot
    from bot import register_handlers

    bot = WebhookBot(token=TELEGRAM_TOKEN)
    bot.start(register_handlers)
    bot.set_webhook("https://your-app.example/telegram/webhook/<secret>",
                    secret_token="optional-header-secret")

    @app.post("/telegram/webhook/<secret>")
    def webhook_view(secret):
        ...verify secret + Telegram secret_token header...
        bot.process_update_dict(request.get_json(force=True))
        return "", 200
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WebhookBot:
    """Owns a PTB v20 Application running in a background asyncio loop.

    Thread model:
      - One daemon thread runs an asyncio event loop forever.
      - Flask request handlers (running in Flask's thread pool) submit
        coroutines via `asyncio.run_coroutine_threadsafe()` and block
        until the future resolves.
      - This means each in-flight webhook ties up one Flask worker for
        as long as the handler runs. For typical command handlers
        (a single Telegram API call) that's tens of milliseconds.
    """

    def __init__(self, token: str, dispatch_timeout: float = 30.0):
        if not token:
            raise ValueError("WebhookBot requires a non-empty TELEGRAM_TOKEN")
        self._token = token
        self._dispatch_timeout = dispatch_timeout
        self._app = None  # telegram.ext.Application
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._started = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self, register_handlers: Callable[[object], None]) -> None:
        """Build the Application, register handlers, start the bg loop.
        `register_handlers(application)` is the user-supplied callback that
        adds CommandHandler/MessageHandler/etc. to the Application."""
        if self._started:
            return

        # Lazy import — pulls in telegram lib only when webhook mode is used.
        from telegram.ext import ApplicationBuilder

        self._app = (
            ApplicationBuilder()
            .token(self._token)
            .updater(None)  # no Updater — we feed updates via process_update
            .build()
        )
        register_handlers(self._app)

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop_forever,
            name="telegram-webhook-loop",
            daemon=True,
        )
        self._loop_thread.start()

        # Initialise + start the application on the bg loop, blocking briefly
        # so we surface init errors at app startup rather than per-request.
        future = asyncio.run_coroutine_threadsafe(self._init_and_start(), self._loop)
        future.result(timeout=15)
        self._started = True
        logger.info("WebhookBot started: bot=@%s", self._app.bot.username if self._app.bot.username else "?")

    def stop(self) -> None:
        """Best-effort shutdown. Safe to call on a not-started bot."""
        if not self._started or self._loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._stop_app(), self._loop)
            future.result(timeout=10)
        except Exception:
            logger.exception("WebhookBot shutdown error")
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._started = False

    # ── Public dispatch API used by Flask handler ──────────────────────

    def process_update_dict(self, payload: dict) -> None:
        """Submit a Telegram Update (already JSON-decoded) for processing.
        Blocks until PTB has dispatched it through registered handlers, or
        until `dispatch_timeout` seconds — whichever is first."""
        if not self._started or self._app is None or self._loop is None:
            raise RuntimeError("WebhookBot.start() must be called first")
        from telegram import Update
        update = Update.de_json(payload, self._app.bot)
        if update is None:
            logger.warning("Telegram payload could not be parsed into Update; skipping")
            return
        future = asyncio.run_coroutine_threadsafe(
            self._app.process_update(update), self._loop
        )
        future.result(timeout=self._dispatch_timeout)

    # ── Telegram-side webhook configuration ────────────────────────────

    def set_webhook(self, url: str, secret_token: Optional[str] = None) -> None:
        """Tell Telegram to deliver updates to `url`.

        If `secret_token` is set, Telegram includes it in the
        X-Telegram-Bot-Api-Secret-Token header on every webhook request,
        and the Flask handler should verify it before processing.
        """
        if not self._started or self._loop is None:
            raise RuntimeError("WebhookBot.start() must be called first")

        async def _set():
            await self._app.bot.set_webhook(
                url=url,
                secret_token=secret_token,
                drop_pending_updates=False,
                allowed_updates=None,  # default — receive everything
            )

        future = asyncio.run_coroutine_threadsafe(_set(), self._loop)
        future.result(timeout=10)
        logger.info("Telegram webhook registered: %s", url)

    def delete_webhook(self) -> None:
        """Unregister the webhook on Telegram side (e.g. switching back to polling)."""
        if not self._started or self._loop is None:
            return

        async def _del():
            await self._app.bot.delete_webhook(drop_pending_updates=False)

        future = asyncio.run_coroutine_threadsafe(_del(), self._loop)
        future.result(timeout=10)
        logger.info("Telegram webhook deleted")

    # ── Internals ──────────────────────────────────────────────────────

    def _run_loop_forever(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _init_and_start(self) -> None:
        await self._app.initialize()
        await self._app.start()

    async def _stop_app(self) -> None:
        try:
            await self._app.stop()
        finally:
            await self._app.shutdown()
