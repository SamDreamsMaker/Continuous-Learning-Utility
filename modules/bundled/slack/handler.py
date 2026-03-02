"""Slack webhook notification module for CLU."""

import logging

from modules.base import BaseModule, ModuleContext

logger = logging.getLogger(__name__)


class SlackModule(BaseModule):

    @property
    def name(self) -> str:
        return "slack"

    async def start(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        url = ctx.config.get("webhook_url", "")
        self._notifier = None
        if url:
            from daemon.notifiers import SlackNotifier
            self._notifier = SlackNotifier(url)
        logger.info("Slack module started (configured: %s)", bool(url))

    async def stop(self) -> None:
        logger.info("Slack module stopped")

    def send(self, title: str, message: str, level: str = "info") -> bool:
        """Send a notification via Slack webhook."""
        if self._notifier:
            return self._notifier.send(title, message, level)
        return False

    def status(self) -> dict:
        return {"running": True, "configured": self._notifier is not None}
