"""WhatsApp Business Cloud API module for CLU.

Receives text and voice messages via webhook, enqueues them as tasks,
and sends a confirmation reply. Voice messages are transcribed via
OpenAI Whisper API if configured.

Setup:
1. Create a Meta Developer app with WhatsApp product
2. Get a permanent access token + phone number ID
3. Configure webhook URL: https://your-server/api/modules/whatsapp/webhook
4. Set verify token to match config (default: "clu")
"""

import hashlib
import hmac
import io
import json
import logging

import httpx

from modules.base import BaseModule, ModuleContext

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"


class WhatsAppModule(BaseModule):

    @property
    def name(self) -> str:
        return "whatsapp"

    async def start(self, ctx: ModuleContext) -> None:
        self._ctx = ctx
        self._access_token = ctx.config.get("access_token", "")
        self._phone_id = ctx.config.get("phone_number_id", "")
        self._app_secret = ctx.config.get("app_secret", "")
        self._verify_token = ctx.config.get("webhook_verify_token", "clu")
        self._whisper_key = ctx.config.get("whisper_api_key", "")
        self._whisper_model = ctx.config.get("whisper_model", "whisper-1")

        if not self._access_token or not self._phone_id:
            logger.warning("WhatsApp module: access_token or phone_number_id not configured")

        # Register webhook endpoints on FastAPI app
        from fastapi import Query, Request
        from fastapi.responses import JSONResponse, PlainTextResponse

        @ctx.app.get("/api/modules/whatsapp/webhook")
        async def whatsapp_verify(
            request: Request,
        ):
            """Webhook verification challenge (Meta requires this for setup)."""
            mode = request.query_params.get("hub.mode")
            token = request.query_params.get("hub.verify_token")
            challenge = request.query_params.get("hub.challenge")

            if mode == "subscribe" and token == self._verify_token:
                logger.info("WhatsApp webhook verified")
                return PlainTextResponse(challenge)
            return JSONResponse({"error": "Verification failed"}, status_code=403)

        @ctx.app.post("/api/modules/whatsapp/webhook")
        async def whatsapp_webhook(request: Request):
            """Receive incoming WhatsApp messages."""
            body = await request.body()

            # Verify signature
            signature = request.headers.get("X-Hub-Signature-256", "")
            if self._app_secret and not self._verify_signature(body, signature):
                logger.warning("WhatsApp webhook: invalid signature")
                return JSONResponse({"error": "Invalid signature"}, status_code=401)

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)

            await self._process_payload(payload)
            return {"ok": True}

        logger.info("WhatsApp module started (phone: %s)", self._phone_id or "not configured")

    async def stop(self) -> None:
        logger.info("WhatsApp module stopped")

    def status(self) -> dict:
        return {
            "running": True,
            "phone_number_id": self._phone_id or "not configured",
            "stt_enabled": bool(self._whisper_key),
        }

    # ---- Signature verification ----

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Meta webhook X-Hub-Signature-256."""
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self._app_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    # ---- Message processing ----

    async def _process_payload(self, payload: dict):
        """Parse WhatsApp webhook payload and enqueue tasks."""
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    await self._handle_message(msg)

    async def _handle_message(self, msg: dict):
        """Process a single incoming message."""
        from_number = msg.get("from", "unknown")
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")

        text = ""
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "audio":
            text = await self._transcribe_audio(msg.get("audio", {}))
        elif msg_type == "image":
            caption = msg.get("image", {}).get("caption", "")
            text = f"[Image received]{': ' + caption if caption else ''}"
        else:
            text = f"[{msg_type} message received]"

        if not text:
            return

        # Enqueue as task
        task_text = text
        task_id = self._ctx.task_queue.enqueue(
            task_text=task_text,
            project_path=self._ctx.project_path,
            priority=5,
            task_type="webhook",
            metadata={
                "source": "whatsapp",
                "from": from_number,
                "message_id": msg_id,
                "message_type": msg_type,
            },
        )
        logger.info("WhatsApp message from %s → task #%d", from_number, task_id)

        # Send confirmation reply
        await self._send_reply(from_number, f"Task #{task_id} received. Processing...")

    # ---- Voice transcription ----

    async def _transcribe_audio(self, audio: dict) -> str:
        """Download WhatsApp audio and transcribe via Whisper."""
        media_id = audio.get("id", "")
        if not media_id:
            return "[Voice message — no media ID]"

        if not self._whisper_key:
            logger.info("Voice message received but no whisper_api_key configured")
            return "[Voice message — STT not configured]"

        try:
            # Step 1: Get media URL from WhatsApp
            async with httpx.AsyncClient() as client:
                media_resp = await client.get(
                    f"{GRAPH_API}/{media_id}",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                media_resp.raise_for_status()
                media_url = media_resp.json().get("url", "")

                if not media_url:
                    return "[Voice message — could not get media URL]"

                # Step 2: Download audio file
                audio_resp = await client.get(
                    media_url,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                audio_resp.raise_for_status()
                audio_bytes = audio_resp.content

                # Step 3: Transcribe via OpenAI Whisper API
                transcript = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._whisper_key}"},
                    files={"file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg")},
                    data={"model": self._whisper_model},
                )
                transcript.raise_for_status()
                text = transcript.json().get("text", "")
                logger.info("Transcribed voice message: %s", text[:80])
                return text or "[Voice message — empty transcription]"

        except Exception as e:
            logger.error("Voice transcription failed: %s", e)
            return f"[Voice message — transcription error: {e}]"

    # ---- Send reply ----

    async def _send_reply(self, to_number: str, text: str):
        """Send a text message reply via WhatsApp Business API."""
        if not self._access_token or not self._phone_id:
            return

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{GRAPH_API}/{self._phone_id}/messages",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": to_number,
                        "type": "text",
                        "text": {"body": text},
                    },
                )
                resp.raise_for_status()
                logger.info("Reply sent to %s", to_number)
        except Exception as e:
            logger.error("Failed to send WhatsApp reply to %s: %s", to_number, e)
