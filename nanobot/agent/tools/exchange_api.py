"""Exchange API tools: reply, forward, mark-read, and create-draft operations."""

from typing import Any

from nanobot.agent.tools.base import Tool


class ExchangeReplyTool(Tool):
    """Reply to an Exchange email via the Exchange API."""

    name = "exchange_reply"
    description = (
        "Reply to an Exchange email. Sends the reply via the Exchange server. "
        "Use this after the user approves a draft reply."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Original email ID to reply to"},
            "body": {"type": "string", "description": "Reply body (HTML or plain text)"},
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipient email addresses (defaults to original sender)",
            },
            "cc": {
                "type": "array",
                "items": {"type": "string"},
                "description": "CC email addresses (optional)",
            },
        },
        "required": ["email_id", "body"],
    }

    def __init__(self, exchange_client: Any):
        self._client = exchange_client

    async def execute(self, email_id: str, body: str, to: list[str] | None = None,
                      cc: list[str] | None = None, **kwargs: Any) -> str:
        try:
            success = await self._client.reply_email(email_id, body, to=to, cc=cc)
            if success:
                return f"Reply sent successfully for email {email_id}"
            return f"Error: Failed to send reply for email {email_id}"
        except Exception as e:
            return f"Error: {e}"


class ExchangeForwardTool(Tool):
    """Forward an Exchange email."""

    name = "exchange_forward"
    description = "Forward an Exchange email to specified recipients."
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Email ID to forward"},
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipient email addresses",
            },
            "body": {"type": "string", "description": "Additional message body to include"},
        },
        "required": ["email_id", "to", "body"],
    }

    def __init__(self, exchange_client: Any):
        self._client = exchange_client

    async def execute(self, email_id: str, to: list[str], body: str, **kwargs: Any) -> str:
        try:
            success = await self._client.forward_email(email_id, to, body)
            if success:
                return f"Email {email_id} forwarded to {', '.join(to)}"
            return f"Error: Failed to forward email {email_id}"
        except Exception as e:
            return f"Error: {e}"


class ExchangeMarkReadTool(Tool):
    """Mark an Exchange email as read."""

    name = "exchange_mark_read"
    description = "Mark an Exchange email as read on the server."
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Email ID to mark as read"},
        },
        "required": ["email_id"],
    }

    def __init__(self, exchange_client: Any):
        self._client = exchange_client

    async def execute(self, email_id: str, **kwargs: Any) -> str:
        try:
            success = await self._client.mark_as_read(email_id)
            return f"Email marked as read: {success}"
        except Exception as e:
            return f"Error: {e}"
