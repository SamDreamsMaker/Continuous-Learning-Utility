"""Desktop notification module for CLU.

Cross-platform: Windows toast, macOS osascript, Linux notify-send.
"""

import logging

from modules.base import BaseModule, ModuleContext

logger = logging.getLogger(__name__)


class DesktopNotifyModule(BaseModule):

    @property
    def name(self) -> str:
        return "desktop-notify"

    async def start(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        from daemon.notifiers import DesktopNotifier
        self._notifier = DesktopNotifier()
        logger.info("Desktop notification module started")

    async def stop(self) -> None:
        logger.info("Desktop notification module stopped")

    def send(self, title: str, message: str, level: str = "info") -> bool:
        """Send an OS desktop notification."""
        if self._notifier:
            return self._notifier.send(title, message, level)
        return False

    def status(self) -> dict:
        import sys
        return {"running": True, "platform": sys.platform}
