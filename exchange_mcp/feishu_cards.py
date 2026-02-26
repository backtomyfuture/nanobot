"""Feishu card sending and updating via Lark API."""

import json
import re
from typing import Any

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


class FeishuCardSender:
    """Send and update interactive cards via Lark API."""

    def __init__(self, app_id: str, app_secret: str, chat_id: str):
        self._chat_id = chat_id
        self._client: Any = None
        if LARK_AVAILABLE and app_id and app_secret:
            self._client = lark_oapi.Client.builder() \
                .app_id(app_id).app_secret(app_secret) \
                .log_level(lark_oapi.LogLevel.WARNING).build()

    def send_card(self, card_json: dict) -> str | None:
        if not self._client:
            return None
        content = json.dumps(card_json, ensure_ascii=False)
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self._chat_id)
                .msg_type("interactive")
                .content(content).build()
            ).build()
        response = self._client.im.v1.message.create(request)
        if response.success():
            return response.data.message_id if response.data else None
        return None

    def update_card(self, message_id: str, card_json: dict) -> bool:
        if not self._client:
            return False
        content = json.dumps(card_json, ensure_ascii=False)
        request = PatchMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(PatchMessageRequestBody.builder().content(content).build()) \
            .build()
        response = self._client.im.v1.message.patch(request)
        return response.success()


def build_approval_card(email_id: str, draft: str, email_data: dict, classification: dict) -> dict:
    subject = email_data.get("subject", "No Subject")
    subject = re.sub(r"^(Subject|主题)[:：]\s*", "", subject, flags=re.IGNORECASE).strip()
    sender = str(email_data.get("sender", "Unknown"))
    summary = classification.get("summary", "")
    reason = classification.get("reasoning", "智能生成")
    is_forward = classification.get("action") == "forward"
    title = f"📬 拟定转发: {subject}" if is_forward else f"📬 拟稿审批: {subject}"
    approve_text = "✅ 批准转发" if is_forward else "✅ 批准发送"

    return {
        "header": {"template": "blue", "title": {"content": title, "tag": "plain_text"}},
        "elements": [
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"💡 AI: {reason}"}]},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**👤 发件人:** {_name(sender)}"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**📄 摘要:**\n*{summary or _snippet(email_data.get('body', ''))}*"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**✍️ {'拟定转发语' if is_forward else '拟定回复'}:**"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": draft or "*(空)*"}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": approve_text}, "type": "primary", "value": {"action": "approve", "id": email_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "✏️ 编辑"}, "type": "default", "value": {"action": "edit_draft", "id": email_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "💾 存为草稿"}, "type": "default", "value": {"action": "save_draft_only", "id": email_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "🛑 拒绝"}, "type": "danger", "value": {"action": "reject", "id": email_id}},
            ]},
        ],
    }


def build_read_only_card(email_id: str, email_data: dict, classification: dict) -> dict:
    subject = email_data.get("subject", "No Subject")
    subject = re.sub(r"^(Subject|主题)[:：]\s*", "", subject, flags=re.IGNORECASE).strip()
    sender = str(email_data.get("sender", "Unknown"))
    summary = classification.get("summary", "")
    reason = classification.get("reasoning", "智能生成")
    priority = classification.get("priority", "P1")
    emoji = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "⚪"}.get(priority, "📧")

    return {
        "header": {"template": "purple", "title": {"content": f"{emoji} 重要邮件: {subject}", "tag": "plain_text"}},
        "elements": [
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"💡 AI: {reason}（无需回复）"}]},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**👤 发件人:** {_name(sender)}"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**📄 内容摘要:**\n*{summary or _snippet(email_data.get('body', ''), 300)}*"}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 已阅"}, "type": "primary", "value": {"action": "mark_read", "id": email_id}},
            ]},
        ],
    }


def build_processed_card(status_text: str, subject: str = "") -> dict:
    return {
        "header": {"title": {"content": f"{status_text} | {subject}", "tag": "plain_text"}, "template": "grey"},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "✅ 已处理完成。"}}],
    }


def _name(raw: str) -> str:
    m = re.search(r"name='(.*?)'", raw)
    if m:
        return m.group(1)
    m2 = re.search(r"email_address='(.*?)'", raw)
    if m2:
        return m2.group(1).split("@")[0]
    if "@" in raw:
        return raw.split("@")[0]
    return raw[:30]


def _snippet(body: str, max_len: int = 200) -> str:
    if not body:
        return "无内容摘要"
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "..." if len(text) > max_len else text or "无内容摘要"
