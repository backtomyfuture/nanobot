"""Exchange email channel: receives emails via polling, pushes to nanobot MessageBus.

Configuration is read from ~/.nanobot/exchange.json (independent of nanobot's config.json).
All processing logic is handled by the MCP server (exchange_mcp); this channel only receives.
"""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

# --- Self-contained config (no schema.py dependency) ---

_CONFIG_PATH = Path.home() / ".nanobot" / "exchange.json"


class _ExchangeConfig:
    """Lightweight config loaded from ~/.nanobot/exchange.json."""

    def __init__(self, data: dict[str, Any] | None = None):
        d = data or {}
        self.enabled: bool = d.get("enabled", False)
        self.api_url: str = d.get("apiUrl", d.get("api_url", ""))
        self.api_key: str = d.get("apiKey", d.get("api_key", ""))
        self.account_id: int = d.get("accountId", d.get("account_id", 0))
        self.ssl_verify: bool = d.get("sslVerify", d.get("ssl_verify", False))
        self.polling_interval: int = d.get("pollingInterval", d.get("polling_interval", 300))
        self.allow_from: list[str] = d.get("allowFrom", d.get("allow_from", []))


def load_exchange_config() -> _ExchangeConfig:
    """Load exchange config from its own JSON file. Returns disabled config if file missing."""
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            return _ExchangeConfig(data)
        except Exception as e:
            logger.warning("Failed to parse {}: {}", _CONFIG_PATH, e)
    return _ExchangeConfig()


# --- Exchange HTTP Client (minimal, polling only) ---

class _ExchangePoller:
    """Minimal HTTP client for polling unread emails."""

    def __init__(self, cfg: _ExchangeConfig):
        self.api_url = cfg.api_url.rstrip("/")
        self.api_key = cfg.api_key
        self.account_id = cfg.account_id
        self.ssl_verify = cfg.ssl_verify

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key} if self.api_key else {}

    async def get_recent_emails(self, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "account_id": self.account_id, "folder": "INBOX",
            "limit": limit, "unread_only": "True",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.get(f"{self.api_url}/list", params=params, headers=self._headers)
            if resp.status_code != 200:
                logger.error("Exchange list failed: {}", resp.status_code)
                return []
            items = resp.json().get("data", {}).get("items", [])
            results = []
            for item in items:
                eid = item.get("id")
                if not eid:
                    continue
                detail = await self._get_detail(eid, client)
                if detail:
                    results.append(detail)
            return results

    async def _get_detail(self, email_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
        encoded = quote(email_id, safe="")
        resp = await client.get(
            f"{self.api_url}/{encoded}",
            params={"account_id": self.account_id}, headers=self._headers, timeout=20.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            if data and "id" not in data:
                data["id"] = email_id
            return data
        return {}

    async def mark_as_read(self, email_id: str) -> bool:
        encoded = quote(email_id, safe="")
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=10.0) as client:
            resp = await client.put(
                f"{self.api_url}/{encoded}/read",
                params={"account_id": self.account_id, "is_read": True},
                headers=self._headers,
            )
            return resp.status_code == 200


# --- Channel ---

class ExchangeChannel(BaseChannel):
    """
    Exchange email channel — polling mode.

    Polls Exchange API for unread emails and pushes them into the nanobot MessageBus.
    All processing (classification, drafting, approval) is handled by the agent
    using MCP tools (exchange_mcp) guided by the exchange-email skill.
    """

    name = "exchange"

    def __init__(self, config: _ExchangeConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: _ExchangeConfig = config
        self._poller = _ExchangePoller(config)
        self._processed_ids: set[str] = set()
        self._MAX_PROCESSED = 50000

    async def start(self) -> None:
        if not self.config.api_url:
            logger.warning("Exchange channel: api_url not configured")
            return

        self._running = True
        interval = max(30, self.config.polling_interval)
        logger.info("Exchange channel started (polling every {}s)", interval)

        while self._running:
            try:
                emails = await self._poller.get_recent_emails()
                for email_data in emails:
                    email_id = email_data.get("id", "")
                    if not email_id or email_id in self._processed_ids:
                        continue

                    self._processed_ids.add(email_id)
                    if len(self._processed_ids) > self._MAX_PROCESSED:
                        self._processed_ids = set(list(self._processed_ids)[self._MAX_PROCESSED // 2:])

                    content = self._format(email_data)
                    await self._handle_message(
                        sender_id=f"exchange:{email_id}",
                        chat_id=f"exchange:{email_id}",
                        content=content,
                        metadata={
                            "email_id": email_id,
                            "subject": email_data.get("subject", ""),
                            "sender": str(email_data.get("sender", "")),
                            "source": "exchange",
                        },
                    )
                    logger.info("Exchange: queued email — {}", email_data.get("subject", "")[:60])
                    await self._poller.mark_as_read(email_id)

            except Exception as e:
                logger.error("Exchange polling error: {}", e)

            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: Any) -> None:
        pass

    @staticmethod
    def _format(email_data: dict[str, Any]) -> str:
        parts = ["[Exchange Email Received]"]
        parts.append(f"ID: {email_data.get('id', 'unknown')}")
        parts.append(f"From: {email_data.get('sender', 'unknown')}")
        to_list = email_data.get("to", [])
        if isinstance(to_list, list):
            parts.append(f"To: {', '.join(str(t) for t in to_list)}")
        parts.append(f"Subject: {email_data.get('subject', '(no subject)')}")
        parts.append(f"Date: {email_data.get('received_at', '')}")
        attachments = email_data.get("attachments", [])
        if attachments:
            parts.append(f"Attachments: {', '.join(a.get('name', '?') for a in attachments)}")
        body = email_data.get("body", "")
        if body:
            parts.append(f"\nBody:\n{body[:8000]}")
        return "\n".join(parts)
