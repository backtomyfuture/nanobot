"""Exchange email channel: receives emails via polling and optional webhook."""

import asyncio
import hashlib
import hmac
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ExchangeChannelConfig


class ExchangeClient:
    """HTTP client for the Exchange API gateway."""

    def __init__(self, config: ExchangeChannelConfig):
        self.api_url = config.api_url.rstrip("/")
        self.api_key = config.api_key
        self.account_id = config.account_id
        self.ssl_verify = config.ssl_verify
        self._folder_cache: dict[str, str] | None = None
        self._folder_policies: dict[str, str] | None = None
        self.sentitems_folder_id: str | None = None
        self.drafts_folder_id: str | None = None
        self._sentitems_name = config.folder_sent_items
        self._drafts_name = config.folder_drafts

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key} if self.api_key else {}

    async def get_recent_emails(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch unread emails from inbox with full details."""
        params = {
            "account_id": self.account_id,
            "folder": "INBOX",
            "limit": limit,
            "unread_only": "True",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.get(
                f"{self.api_url}/list", params=params, headers=self._headers
            )
            if resp.status_code != 200:
                logger.error("Exchange list failed: {} - {}", resp.status_code, resp.text[:200])
                return []
            items = resp.json().get("data", {}).get("items", [])
            results = []
            for item in items:
                email_id = item.get("id")
                if not email_id:
                    continue
                detail = await self.get_email(email_id)
                if detail:
                    results.append(detail)
            return results

    async def get_email(self, email_id: str) -> dict[str, Any]:
        """Fetch full email details by ID."""
        encoded = quote(email_id, safe="")
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=20.0) as client:
            resp = await client.get(
                f"{self.api_url}/{encoded}",
                params={"account_id": self.account_id},
                headers=self._headers,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if data and "id" not in data:
                    data["id"] = email_id
                return data
            logger.error("Exchange get_email failed for {}: {}", email_id, resp.status_code)
        return {}

    async def reply_email(
        self, email_id: str, body: str, to: list[str] | None = None, cc: list[str] | None = None
    ) -> bool:
        """Reply to an email."""
        payload: dict[str, Any] = {
            "account_id": self.account_id,
            "reference_item_id": email_id,
            "body": body,
            "body_type": "html",
        }
        if to:
            payload["to"] = to
        if cc:
            payload["cc"] = cc
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.post(
                f"{self.api_url}/reply", json=payload, headers=self._headers
            )
            if resp.status_code == 200:
                return resp.json().get("code") == 200
            logger.error("Exchange reply failed: {} - {}", resp.status_code, resp.text[:200])
        return False

    async def forward_email(self, email_id: str, to: list[str], body: str) -> bool:
        """Forward an email."""
        payload = {
            "account_id": self.account_id,
            "reference_item_id": email_id,
            "to": to,
            "body": body,
            "body_type": "html",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.post(
                f"{self.api_url}/forward", json=payload, headers=self._headers
            )
            if resp.status_code == 200:
                return resp.json().get("code") == 200
            logger.error("Exchange forward failed: {} - {}", resp.status_code, resp.text[:200])
        return False

    async def mark_as_read(self, email_id: str) -> bool:
        """Mark an email as read."""
        encoded = quote(email_id, safe="")
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=10.0) as client:
            resp = await client.put(
                f"{self.api_url}/{encoded}/read",
                params={"account_id": self.account_id, "is_read": True},
                headers=self._headers,
            )
            if resp.status_code == 200:
                return resp.json().get("code") == 200
        return False

    async def create_draft(
        self, to: list[str], subject: str, body: str, cc: list[str] | None = None
    ) -> bool:
        """Create a draft email."""
        payload = {
            "account_id": self.account_id,
            "to": to,
            "cc": cc or [],
            "subject": subject,
            "body": body,
            "body_type": "html",
            "folder": "Drafts",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=10.0) as client:
            resp = await client.post(
                f"{self.api_url}/drafts", json=payload, headers=self._headers
            )
            return resp.status_code == 200


class ExchangeChannel(BaseChannel):
    """
    Exchange email channel.

    Inbound: polls Exchange API for unread emails (webhook support planned).
    Outbound: replies/forwards via Exchange API.
    """

    name = "exchange"

    def __init__(self, config: ExchangeChannelConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: ExchangeChannelConfig = config
        self.client = ExchangeClient(config)
        self._processed_ids: set[str] = set()
        self._MAX_PROCESSED = 50000

    async def start(self) -> None:
        """Start polling for new Exchange emails."""
        if not self.config.api_url:
            logger.warning("Exchange channel: api_url not configured, channel disabled")
            return

        self._running = True
        interval = max(30, self.config.polling_interval) if self.config.polling_interval > 0 else 300
        logger.info("Exchange channel started (polling every {}s)", interval)

        while self._running:
            try:
                emails = await self.client.get_recent_emails(limit=20)
                for email_data in emails:
                    email_id = email_data.get("id", "")
                    if not email_id or email_id in self._processed_ids:
                        continue

                    self._processed_ids.add(email_id)
                    if len(self._processed_ids) > self._MAX_PROCESSED:
                        self._processed_ids = set(list(self._processed_ids)[self._MAX_PROCESSED // 2:])

                    content = self._format_email_content(email_data)
                    metadata = {
                        "email_id": email_id,
                        "subject": email_data.get("subject", ""),
                        "sender": str(email_data.get("sender", "")),
                        "to": email_data.get("to", []),
                        "cc": email_data.get("cc", []),
                        "received_at": email_data.get("received_at", ""),
                        "attachments": [
                            a.get("name", "unknown") for a in email_data.get("attachments", [])
                        ],
                        "has_attachments": bool(email_data.get("attachments")),
                        "source": "exchange",
                    }

                    await self._handle_message(
                        sender_id=f"exchange:{email_id}",
                        chat_id=f"exchange:{email_id}",
                        content=content,
                        metadata=metadata,
                    )
                    logger.info("Exchange: new email queued - {}", email_data.get("subject", "")[:60])

                    await self.client.mark_as_read(email_id)

            except Exception as e:
                logger.error("Exchange polling error: {}", e)

            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Handle outbound actions (reply, forward, etc)."""
        action = (msg.metadata or {}).get("exchange_action")
        email_id = (msg.metadata or {}).get("email_id", "")

        if action == "reply":
            to = (msg.metadata or {}).get("to", [])
            cc = (msg.metadata or {}).get("cc", [])
            success = await self.client.reply_email(email_id, msg.content, to=to, cc=cc)
            logger.info("Exchange reply {}: {}", "ok" if success else "FAILED", email_id[:40])
        elif action == "forward":
            to = (msg.metadata or {}).get("to", [])
            success = await self.client.forward_email(email_id, to, msg.content)
            logger.info("Exchange forward {}: {}", "ok" if success else "FAILED", email_id[:40])
        elif action == "draft":
            to = (msg.metadata or {}).get("to", [])
            cc = (msg.metadata or {}).get("cc", [])
            subject = (msg.metadata or {}).get("subject", "")
            await self.client.create_draft(to, subject, msg.content, cc=cc)
        else:
            logger.debug("Exchange send: no action specified, ignoring")

    @staticmethod
    def _format_email_content(email_data: dict[str, Any]) -> str:
        """Format email data into a structured text for the agent."""
        parts = ["[Exchange Email Received]"]
        parts.append(f"ID: {email_data.get('id', 'unknown')}")
        parts.append(f"From: {email_data.get('sender', 'unknown')}")

        to_list = email_data.get("to", [])
        if isinstance(to_list, list):
            parts.append(f"To: {', '.join(str(t) for t in to_list)}")
        else:
            parts.append(f"To: {to_list}")

        cc_list = email_data.get("cc", [])
        if cc_list:
            if isinstance(cc_list, list):
                parts.append(f"CC: {', '.join(str(c) for c in cc_list)}")
            else:
                parts.append(f"CC: {cc_list}")

        parts.append(f"Subject: {email_data.get('subject', '(no subject)')}")
        parts.append(f"Date: {email_data.get('received_at', 'unknown')}")

        attachments = email_data.get("attachments", [])
        if attachments:
            att_names = [a.get("name", "unknown") for a in attachments]
            parts.append(f"Attachments: {', '.join(att_names)}")

        body = email_data.get("body", "")
        if body:
            if len(body) > 8000:
                body = body[:8000] + "\n...(truncated)"
            parts.append(f"\nBody:\n{body}")

        return "\n".join(parts)

    @staticmethod
    def verify_webhook_signature(secret: str, body: bytes, signature: str) -> bool:
        """Verify Exchange webhook HMAC-SHA256 signature."""
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
