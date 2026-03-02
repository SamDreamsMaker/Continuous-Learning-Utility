"""Echo module: logs events for testing the module system."""

import logging

from modules.base import BaseModule, ModuleContext

logger = logging.getLogger(__name__)


class EchoModule(BaseModule):
    """Simple test module that logs when started/stopped."""

    @property
    def name(self) -> str:
        return "echo"

    async def start(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        logger.info("Echo module started (project: %s)", ctx.project_path)

    async def stop(self) -> None:
        logger.info("Echo module stopped")

    def status(self) -> dict:
        return {"running": True, "message": "Echo module is active"}
