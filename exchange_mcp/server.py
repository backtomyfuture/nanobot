"""Exchange MCP Server — exposes 12 I/O tools for nanobot's Exchange email workflow."""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from exchange_mcp.config import get_config
from exchange_mcp.email_state import list_states, read_state, write_state
from exchange_mcp.exchange_client import ExchangeClient
from exchange_mcp.feishu_cards import (
    FeishuCardSender,
    build_approval_card,
    build_processed_card,
    build_read_only_card,
)

logger = logging.getLogger("exchange_mcp")

server = Server("exchange-tools")

_exchange: ExchangeClient | None = None
_qdrant: Any = None
_feishu: FeishuCardSender | None = None


def _get_exchange() -> ExchangeClient:
    global _exchange
    if _exchange is None:
        cfg = get_config()
        _exchange = ExchangeClient(cfg.api_url, cfg.api_key, cfg.account_id, cfg.ssl_verify)
    return _exchange


def _get_qdrant():
    global _qdrant
    if _qdrant is None:
        cfg = get_config().qdrant
        if cfg.embedding_base_url and cfg.embedding_model:
            from exchange_mcp.qdrant_tools import QdrantTools
            _qdrant = QdrantTools(
                cfg.url, cfg.collection_name,
                cfg.embedding_api_key, cfg.embedding_base_url, cfg.embedding_model,
            )
    return _qdrant


def _get_feishu() -> FeishuCardSender | None:
    global _feishu
    if _feishu is None:
        cfg = get_config().feishu
        if cfg.app_id and cfg.app_secret:
            _feishu = FeishuCardSender(cfg.app_id, cfg.app_secret, cfg.chat_id)
    return _feishu


def _text(content: str) -> list[TextContent]:
    return [TextContent(type="text", text=content)]


# --- Tool Definitions ---

TOOLS = [
    Tool(name="exchange_reply", description="Reply to an Exchange email",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID to reply to"},
             "body": {"type": "string", "description": "Reply body (HTML or text)"},
             "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients (optional)"},
             "cc": {"type": "array", "items": {"type": "string"}, "description": "CC (optional)"},
         }, "required": ["email_id", "body"]}),
    Tool(name="exchange_forward", description="Forward an Exchange email",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID to forward"},
             "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients"},
             "body": {"type": "string", "description": "Forward message body"},
         }, "required": ["email_id", "to", "body"]}),
    Tool(name="exchange_mark_read", description="Mark an Exchange email as read",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID"},
         }, "required": ["email_id"]}),
    Tool(name="email_state_read", description="Read processing state of an email",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID"},
         }, "required": ["email_id"]}),
    Tool(name="email_state_write", description="Save processing state of an email",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID"},
             "status": {"type": "string", "description": "Status (pending/classified/drafted/waiting_approval/approved/rejected/sent/error/archived)"},
             "classification": {"type": "object", "description": "Classification result (optional)"},
             "draft": {"type": "string", "description": "Draft content (optional)"},
             "subject": {"type": "string", "description": "Subject (optional)"},
             "sender": {"type": "string", "description": "Sender (optional)"},
             "message_id": {"type": "string", "description": "Feishu card message_id (optional)"},
         }, "required": ["email_id", "status"]}),
    Tool(name="email_state_list", description="List recent email processing states",
         inputSchema={"type": "object", "properties": {
             "status_filter": {"type": "string", "description": "Filter by status (optional)"},
             "limit": {"type": "integer", "description": "Max results (default 20)"},
         }}),
    Tool(name="qdrant_search", description="Search historical emails by semantic similarity",
         inputSchema={"type": "object", "properties": {
             "query": {"type": "string", "description": "Search query"},
             "sender": {"type": "string", "description": "Filter by sender (optional)"},
             "thread_id": {"type": "string", "description": "Thread ID (optional)"},
             "limit": {"type": "integer", "description": "Max results (default 5)"},
         }, "required": ["query"]}),
    Tool(name="qdrant_ingest", description="Index an email into vector database for RAG",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string", "description": "Email ID"},
             "subject": {"type": "string", "description": "Subject"},
             "body": {"type": "string", "description": "Body text"},
             "sender": {"type": "string", "description": "Sender (optional)"},
             "thread_id": {"type": "string", "description": "Thread ID (optional)"},
             "received_at": {"type": "string", "description": "Timestamp (optional)"},
         }, "required": ["email_id", "subject", "body"]}),
    Tool(name="send_approval_card", description="Send Feishu approval card for email draft",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string"}, "draft": {"type": "string"},
             "subject": {"type": "string"}, "sender": {"type": "string"},
             "summary": {"type": "string"}, "priority": {"type": "string"},
             "intent": {"type": "string"}, "reasoning": {"type": "string"},
         }, "required": ["email_id", "draft", "subject", "sender"]}),
    Tool(name="send_notification_card", description="Send Feishu read-only notification card",
         inputSchema={"type": "object", "properties": {
             "email_id": {"type": "string"}, "subject": {"type": "string"},
             "sender": {"type": "string"}, "summary": {"type": "string"},
             "priority": {"type": "string"}, "reasoning": {"type": "string"},
         }, "required": ["email_id", "subject", "sender"]}),
    Tool(name="update_feishu_card", description="Update Feishu card to processed status",
         inputSchema={"type": "object", "properties": {
             "message_id": {"type": "string", "description": "Card message_id to update"},
             "status_text": {"type": "string", "description": "Status (已批准/已拒绝/已阅)"},
             "subject": {"type": "string", "description": "Original subject (optional)"},
         }, "required": ["message_id", "status_text"]}),
    Tool(name="check_new_emails", description="Check Exchange for new unread emails (polling)",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "integer", "description": "Max emails to fetch (default 10)"},
         }}),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "exchange_reply":
            ok = await _get_exchange().reply_email(
                arguments["email_id"], arguments["body"],
                to=arguments.get("to"), cc=arguments.get("cc"),
            )
            return _text(json.dumps({"ok": ok, "email_id": arguments["email_id"]}))

        elif name == "exchange_forward":
            ok = await _get_exchange().forward_email(
                arguments["email_id"], arguments["to"], arguments["body"],
            )
            return _text(json.dumps({"ok": ok, "email_id": arguments["email_id"]}))

        elif name == "exchange_mark_read":
            ok = await _get_exchange().mark_as_read(arguments["email_id"])
            return _text(json.dumps({"ok": ok}))

        elif name == "email_state_read":
            return _text(json.dumps(read_state(arguments["email_id"]), ensure_ascii=False))

        elif name == "email_state_write":
            eid = arguments.pop("email_id")
            status = arguments.pop("status")
            result = write_state(eid, status, **arguments)
            return _text(json.dumps(result, ensure_ascii=False))

        elif name == "email_state_list":
            result = list_states(
                arguments.get("status_filter", ""), arguments.get("limit", 20),
            )
            return _text(json.dumps(result, ensure_ascii=False))

        elif name == "qdrant_search":
            qt = _get_qdrant()
            if not qt:
                return _text(json.dumps({"error": "Qdrant not configured"}))
            result = qt.search(
                arguments["query"], arguments.get("sender", ""),
                arguments.get("thread_id", ""), arguments.get("limit", 5),
            )
            return _text(json.dumps(result, ensure_ascii=False))

        elif name == "qdrant_ingest":
            qt = _get_qdrant()
            if not qt:
                return _text(json.dumps({"error": "Qdrant not configured"}))
            result = qt.ingest(
                arguments["email_id"], arguments["subject"], arguments["body"],
                arguments.get("sender", ""), arguments.get("thread_id", ""),
                arguments.get("received_at", ""),
            )
            return _text(json.dumps(result, ensure_ascii=False))

        elif name == "send_approval_card":
            fs = _get_feishu()
            if not fs:
                return _text(json.dumps({"error": "Feishu not configured"}))
            card = build_approval_card(
                arguments["email_id"], arguments["draft"],
                {"subject": arguments["subject"], "sender": arguments["sender"],
                 "to": [], "cc": [], "attachments": [], "body": ""},
                {"summary": arguments.get("summary", ""), "priority": arguments.get("priority", "P2"),
                 "intent": arguments.get("intent", ""), "reasoning": arguments.get("reasoning", ""),
                 "need_reply": True},
            )
            mid = fs.send_card(card)
            return _text(json.dumps({"ok": bool(mid), "message_id": mid}))

        elif name == "send_notification_card":
            fs = _get_feishu()
            if not fs:
                return _text(json.dumps({"error": "Feishu not configured"}))
            card = build_read_only_card(
                arguments["email_id"],
                {"subject": arguments["subject"], "sender": arguments["sender"],
                 "to": [], "cc": [], "attachments": [], "body": ""},
                {"summary": arguments.get("summary", ""), "priority": arguments.get("priority", "P1"),
                 "reasoning": arguments.get("reasoning", ""), "need_reply": False},
            )
            mid = fs.send_card(card)
            return _text(json.dumps({"ok": bool(mid), "message_id": mid}))

        elif name == "update_feishu_card":
            fs = _get_feishu()
            if not fs:
                return _text(json.dumps({"error": "Feishu not configured"}))
            card = build_processed_card(arguments["status_text"], arguments.get("subject", ""))
            ok = fs.update_card(arguments["message_id"], card)
            return _text(json.dumps({"ok": ok}))

        elif name == "check_new_emails":
            emails = await _get_exchange().get_recent_emails(arguments.get("limit", 10))
            return _text(json.dumps({"count": len(emails), "emails": [
                {"id": e.get("id"), "subject": e.get("subject"), "sender": str(e.get("sender", ""))}
                for e in emails
            ]}, ensure_ascii=False))

        else:
            return _text(f"Unknown tool: {name}")

    except Exception as e:
        logger.exception("Tool %s failed", name)
        return _text(json.dumps({"error": str(e)}))
