"""GitHub webhook module for CLU.

Receives GitHub webhook events (issues, push) and enqueues them as tasks.
Reuses the existing WebhookHandler by composition — no code duplication.

Setup:
1. In your GitHub repo: Settings → Webhooks → Add webhook
2. Payload URL: https://your-server/api/modules/github/webhook
3. Content type: application/json
4. Secret: match your github_secret config (store via --secret CLI)
5. Events: Issues, Push
"""

import json
import logging

from modules.base import BaseModule, ModuleContext

logger = logging.getLogger(__name__)


class GitHubModule(BaseModule):

    @property
    def name(self) -> str:
        return "github"

    async def start(self, ctx: ModuleContext) -> None:
        self._ctx = ctx

        # Reuse existing WebhookHandler (composition)
        from daemon.webhooks import WebhookHandler
        self._handler = WebhookHandler(
            queue=ctx.task_queue,
            project_path=ctx.project_path,
        )

        # Configure secret from keyring/config
        secret = ctx.config.get("github_secret", "")
        if secret:
            self._handler.set_github_secret(secret)

        # Register webhook endpoints on FastAPI
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @ctx.app.post("/api/modules/github/webhook")
        async def github_webhook(request: Request):
            """Receive GitHub webhook events (issues, push)."""
            self._handler.project_path = ctx.project_path

            body = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            event_type = request.headers.get("X-GitHub-Event", "")

            if not self._handler.verify_github_signature(body, signature):
                return JSONResponse({"error": "Invalid signature"}, status_code=401)

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)

            result = self._handler.handle_github(event_type, payload)
            return {
                "ok": result.ok,
                "task_id": result.task_id,
                "message": result.message,
                "skipped": result.skipped,
            }

        @ctx.app.post("/api/modules/github/generic")
        async def generic_webhook(body: dict):
            """Receive a generic webhook with a task payload."""
            self._handler.project_path = ctx.project_path
            result = self._handler.handle_generic(body)
            status_code = 200 if result.ok else 400
            return JSONResponse({
                "ok": result.ok,
                "task_id": result.task_id,
                "message": result.message,
            }, status_code=status_code)

        logger.info("GitHub module started (secret configured: %s)", bool(secret))

    async def stop(self) -> None:
        logger.info("GitHub module stopped")

    def status(self) -> dict:
        return {
            "running": True,
            "secret_configured": bool(
                self._handler._github_secret if hasattr(self, "_handler") else False
            ),
        }
