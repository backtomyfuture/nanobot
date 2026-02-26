"""Email state management tool: JSON file-based persistence for email processing state."""

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


def _state_dir() -> Path:
    """Get the exchange email state directory."""
    d = Path.home() / ".nanobot" / "data" / "exchange" / "emails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(email_id: str) -> str:
    """Convert email ID to a safe filename."""
    safe = email_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    if len(safe) > 200:
        import hashlib
        safe = hashlib.sha256(email_id.encode()).hexdigest()
    return safe


class EmailStateReadTool(Tool):
    """Read the processing state of an email."""

    name = "email_state_read"
    description = (
        "Read the current processing state of an Exchange email by its ID. "
        "Returns the state JSON or 'not_found' if never processed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "The Exchange email ID"},
        },
        "required": ["email_id"],
    }

    async def execute(self, email_id: str, **kwargs: Any) -> str:
        path = _state_dir() / f"{_safe_filename(email_id)}.json"
        if not path.exists():
            return json.dumps({"status": "not_found", "email_id": email_id})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading state: {e}"


class EmailStateWriteTool(Tool):
    """Write or update the processing state of an email."""

    name = "email_state_write"
    description = (
        "Save or update the processing state of an Exchange email. "
        "Use this to record classification results, draft content, approval status, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "The Exchange email ID"},
            "status": {
                "type": "string",
                "description": "Processing status",
                "enum": [
                    "pending", "classified", "drafted", "waiting_approval",
                    "approved", "rejected", "sent", "forwarded",
                    "skipped", "error", "archived",
                ],
            },
            "classification": {
                "type": "object",
                "description": "Classification result (priority, need_reply, intent, summary)",
            },
            "draft": {"type": "string", "description": "Draft reply content"},
            "subject": {"type": "string", "description": "Email subject"},
            "sender": {"type": "string", "description": "Sender address"},
            "error_message": {"type": "string", "description": "Error details if status=error"},
        },
        "required": ["email_id", "status"],
    }

    async def execute(self, email_id: str, status: str, **kwargs: Any) -> str:
        path = _state_dir() / f"{_safe_filename(email_id)}.json"
        try:
            existing: dict[str, Any] = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))

            existing["email_id"] = email_id
            existing["status"] = status
            existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            if "created_at" not in existing:
                existing["created_at"] = existing["updated_at"]

            for key in ("classification", "draft", "subject", "sender", "error_message"):
                if key in kwargs and kwargs[key] is not None:
                    existing[key] = kwargs[key]

            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            return json.dumps({"ok": True, "email_id": email_id, "status": status})
        except Exception as e:
            logger.error("Failed to write email state {}: {}", email_id, e)
            return f"Error writing state: {e}"


class EmailStateListTool(Tool):
    """List recent email processing states."""

    name = "email_state_list"
    description = (
        "List recent email processing states. Useful for generating summaries, "
        "checking pending items, or reviewing processed emails."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "description": "Filter by status (optional). E.g. 'waiting_approval', 'pending'",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 20)",
                "minimum": 1,
                "maximum": 100,
            },
        },
    }

    async def execute(self, status_filter: str = "", limit: int = 20, **kwargs: Any) -> str:
        state_dir = _state_dir()
        results = []
        for p in sorted(state_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            if len(results) >= limit:
                break
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if status_filter and data.get("status") != status_filter:
                    continue
                results.append({
                    "email_id": data.get("email_id", ""),
                    "status": data.get("status", "unknown"),
                    "subject": data.get("subject", ""),
                    "sender": data.get("sender", ""),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                continue
        return json.dumps(results, ensure_ascii=False)
