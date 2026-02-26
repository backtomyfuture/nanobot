"""Feishu interactive card tools for HITL email approval workflow."""

import json
from typing import Any

from loguru import logger

from nanobot.agent.tools._card_builder import (
    build_approval_card,
    build_processed_card,
    build_read_only_card,
)
from nanobot.agent.tools.base import Tool

try:
    import lark_oapi
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        PatchMessageRequest,
        PatchMessageRequestBody,
    )
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False


class _LarkCardSender:
    """Thin wrapper around Lark API client for sending interactive cards."""

    def __init__(self, app_id: str, app_secret: str, chat_id: str):
        self._chat_id = chat_id
        self._client: Any = None
        if LARK_AVAILABLE and app_id and app_secret:
            self._client = lark_oapi.Client.builder() \
                .app_id(app_id) \
                .app_secret(app_secret) \
                .log_level(lark_oapi.LogLevel.WARNING) \
                .build()

    def send_card(self, card_json: dict) -> str | None:
        """Send an interactive card to the configured chat. Returns message_id."""
        if not self._client:
            logger.warning("Lark client not initialized, cannot send card")
            return None
        try:
            content = json.dumps(card_json, ensure_ascii=False)
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(self._chat_id)
                    .msg_type("interactive")
                    .content(content)
                    .build()
                ).build()
            response = self._client.im.v1.message.create(request)
            if response.success():
                msg_id = response.data.message_id if response.data else None
                logger.info("Feishu card sent, message_id={}", msg_id)
                return msg_id
            logger.error("Feishu card send failed: code={}, msg={}", response.code, response.msg)
        except Exception as e:
            logger.error("Error sending Feishu card: {}", e)
        return None

    def update_card(self, message_id: str, card_json: dict) -> bool:
        """Update (patch) an existing card by message_id."""
        if not self._client:
            return False
        try:
            content = json.dumps(card_json, ensure_ascii=False)
            request = PatchMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(content)
                    .build()
                ).build()
            response = self._client.im.v1.message.patch(request)
            if response.success():
                return True
            logger.error("Card patch failed: code={}, msg={}", response.code, response.msg)
        except Exception as e:
            logger.error("Error patching card: {}", e)
        return False


class SendApprovalCardTool(Tool):
    """Send a Feishu interactive approval card for an email draft."""

    name = "send_approval_card"
    description = (
        "Send a Feishu interactive card for email draft approval. "
        "The card includes the email summary, draft reply, and approve/reject/edit buttons. "
        "Returns the message_id of the sent card."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Exchange email ID"},
            "draft": {"type": "string", "description": "Draft reply text"},
            "subject": {"type": "string", "description": "Email subject"},
            "sender": {"type": "string", "description": "Email sender"},
            "summary": {"type": "string", "description": "Email classification summary"},
            "priority": {"type": "string", "description": "Priority level (P0-P3)"},
            "intent": {"type": "string", "description": "Email intent (咨询/审批/通知/垃圾邮件)"},
            "reasoning": {"type": "string", "description": "AI classification reasoning"},
        },
        "required": ["email_id", "draft", "subject", "sender"],
    }

    def __init__(self, card_sender: _LarkCardSender):
        self._sender = card_sender

    async def execute(
        self, email_id: str, draft: str, subject: str, sender: str,
        summary: str = "", priority: str = "P2", intent: str = "咨询",
        reasoning: str = "", **kwargs: Any,
    ) -> str:
        email_data = {"subject": subject, "sender": sender, "to": [], "cc": [], "attachments": []}
        classification = {
            "summary": summary,
            "priority": priority,
            "intent": intent,
            "reasoning": reasoning,
            "need_reply": True,
        }
        card_json = build_approval_card(email_id, draft, email_data, classification)
        msg_id = self._sender.send_card(card_json)
        if msg_id:
            return json.dumps({"ok": True, "message_id": msg_id, "email_id": email_id})
        return "Error: Failed to send approval card"


class SendNotificationCardTool(Tool):
    """Send a Feishu read-only notification card for important emails."""

    name = "send_notification_card"
    description = (
        "Send a Feishu read-only notification card for an important email that doesn't need a reply. "
        "The card shows the email summary with a 'mark read' button."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Exchange email ID"},
            "subject": {"type": "string", "description": "Email subject"},
            "sender": {"type": "string", "description": "Email sender"},
            "summary": {"type": "string", "description": "Email summary"},
            "priority": {"type": "string", "description": "Priority (P0-P3)"},
            "reasoning": {"type": "string", "description": "AI reasoning"},
        },
        "required": ["email_id", "subject", "sender"],
    }

    def __init__(self, card_sender: _LarkCardSender):
        self._sender = card_sender

    async def execute(
        self, email_id: str, subject: str, sender: str,
        summary: str = "", priority: str = "P1", reasoning: str = "",
        **kwargs: Any,
    ) -> str:
        email_data = {"subject": subject, "sender": sender, "to": [], "cc": [], "attachments": []}
        classification = {
            "summary": summary,
            "priority": priority,
            "reasoning": reasoning,
            "need_reply": False,
        }
        card_json = build_read_only_card(email_id, email_data, classification)
        msg_id = self._sender.send_card(card_json)
        if msg_id:
            return json.dumps({"ok": True, "message_id": msg_id, "email_id": email_id})
        return "Error: Failed to send notification card"


class UpdateCardTool(Tool):
    """Update a Feishu card to show processed status."""

    name = "update_feishu_card"
    description = (
        "Update a Feishu card to show that the email has been processed. "
        "Replaces the card content with a simple 'processed' status."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Feishu message_id of the card to update"},
            "status_text": {"type": "string", "description": "Status label (e.g. 已批准, 已拒绝, 已阅)"},
            "subject": {"type": "string", "description": "Original email subject"},
        },
        "required": ["message_id", "status_text"],
    }

    def __init__(self, card_sender: _LarkCardSender):
        self._sender = card_sender

    async def execute(
        self, message_id: str, status_text: str, subject: str = "", **kwargs: Any,
    ) -> str:
        card_json = build_processed_card(status_text, subject)
        success = self._sender.update_card(message_id, card_json)
        if success:
            return json.dumps({"ok": True, "message_id": message_id})
        return "Error: Failed to update card"
