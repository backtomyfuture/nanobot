"""
Feishu/Lark card builder — migrated from AI-Exchange card_builder.py.

Constructs interactive card JSON for approval workflows, read-only
notifications, and processed-state cards. Designed to work standalone
without LangGraph or PostgreSQL dependencies.
"""

from __future__ import annotations

import re
from typing import Any


def extract_email_address(raw: Any) -> str | None:
    """Extract email address from various formats."""
    raw_str = str(raw).strip()
    m = re.search(r"email_address='(.*?)'", raw_str)
    if m:
        return m.group(1)
    m2 = re.search(r"<([^>]+)>", raw_str)
    if m2:
        return m2.group(1)
    if "@" in raw_str and " " not in raw_str:
        return raw_str
    return None


def _format_recipients_text(recipients: list, limit: int = 3) -> str:
    """Format recipient list as display text."""
    if not recipients:
        return "无"
    items = []
    for r in recipients:
        r_str = str(r).strip()
        m = re.search(r"name='(.*?)'", r_str)
        if m:
            items.append(m.group(1))
        else:
            email = extract_email_address(r_str)
            items.append(email or r_str[:30])
    if len(items) > limit:
        return ", ".join(items[:limit]) + f" 等{len(items)}人"
    return ", ".join(items)


def build_approval_card(
    email_id: str,
    draft: str,
    email_data: dict,
    classification: dict,
) -> dict:
    """
    Build an interactive approval card for email replies.

    Features:
    - Email summary with sender/recipient info
    - Draft reply preview
    - Approve / Save Draft / Reject buttons
    - Edit draft button
    """
    subject = email_data.get("subject", "No Subject")
    subject = re.sub(r"^(Subject|主题)[:：]\s*", "", subject, flags=re.IGNORECASE).strip()
    raw_sender = str(email_data.get("sender", "Unknown"))
    to_list = email_data.get("to", [])
    if isinstance(to_list, str):
        to_list = [to_list]
    cc_list = email_data.get("cc", [])
    if isinstance(cc_list, str):
        cc_list = [cc_list]

    summary = classification.get("summary", "")
    reason = classification.get("reasoning", "智能生成")
    is_forward = classification.get("action") == "forward"

    header_title = f"📬 拟定转发: {subject}" if is_forward else f"📬 拟稿审批: {subject}"

    header = {
        "template": "blue",
        "title": {"content": header_title, "tag": "plain_text"},
    }

    elements: list[dict] = []

    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"💡 AI 处理说明: {reason}"}],
    })

    sender_text = f"**👤 发件人:** {_display_name(raw_sender)}"
    to_text = f"**👥 收件人:** {_format_recipients_text(to_list)}"
    info_line = f"{sender_text}  |  {to_text}"
    if cc_list:
        info_line += f"  |  **👀 抄送:** {_format_recipients_text(cc_list)}"
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": info_line}})
    elements.append({"tag": "hr"})

    summary_text = summary or _body_snippet(email_data.get("body", ""), 200)
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**📄 邮件摘要:**\n*{summary_text}*"}})

    attachments = email_data.get("attachments", [])
    if attachments:
        att_names = [a.get("name", "unknown") for a in attachments[:5] if not a.get("content_id")]
        if att_names:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "📎 " + ", ".join(att_names)},
            })

    elements.append({"tag": "hr"})

    draft_label = "**✍️ 拟定转发语:**" if is_forward else "**✍️ 拟定回复:**"
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": draft_label}})
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": draft or "*(空)*"}})

    elements.append({"tag": "hr"})

    approve_text = "✅ 批准转发" if is_forward else "✅ 批准发送"
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button", "text": {"tag": "plain_text", "content": approve_text},
                "type": "primary", "value": {"action": "approve", "id": email_id},
            },
            {
                "tag": "button", "text": {"tag": "plain_text", "content": "✏️ 编辑"},
                "type": "default", "value": {"action": "edit_draft", "id": email_id},
            },
            {
                "tag": "button", "text": {"tag": "plain_text", "content": "💾 存为草稿"},
                "type": "default", "value": {"action": "save_draft_only", "id": email_id},
            },
            {
                "tag": "button", "text": {"tag": "plain_text", "content": "🛑 拒绝"},
                "type": "danger", "value": {"action": "reject", "id": email_id},
            },
        ],
    })

    return {"header": header, "elements": elements}


def build_read_only_card(
    email_id: str,
    email_data: dict,
    classification: dict,
) -> dict:
    """
    Build a read-only notification card for important emails that don't need a reply.
    """
    subject = email_data.get("subject", "No Subject")
    subject = re.sub(r"^(Subject|主题)[:：]\s*", "", subject, flags=re.IGNORECASE).strip()
    raw_sender = str(email_data.get("sender", "Unknown"))

    reason = classification.get("reasoning", "智能生成")
    priority = classification.get("priority", "P1")
    priority_emoji = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "⚪"}.get(priority, "📧")

    header = {
        "template": "purple",
        "title": {"content": f"{priority_emoji} 重要邮件: {subject}", "tag": "plain_text"},
    }

    elements: list[dict] = []

    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"💡 AI 处理说明: {reason}（无需回复）"}],
    })

    sender_text = f"**👤 发件人:** {_display_name(raw_sender)}"
    to_list = email_data.get("to", [])
    to_text = f"**👥 收件人:** {_format_recipients_text(to_list if isinstance(to_list, list) else [to_list])}"
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"{sender_text}  |  {to_text}"}})
    elements.append({"tag": "hr"})

    summary = classification.get("summary", "")
    snippet = summary or _body_snippet(email_data.get("body", ""), 300)
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**📄 邮件内容摘要:**\n*{snippet}*"},
    })

    attachments = email_data.get("attachments", [])
    real_att = [a for a in attachments if not a.get("content_id")]
    if real_att:
        att_names = [a.get("name", "unknown") for a in real_att[:5]]
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "📎 " + ", ".join(att_names)}})

    elements.append({"tag": "hr"})

    elements.append({
        "tag": "action",
        "actions": [{
            "tag": "button", "text": {"tag": "plain_text", "content": "✅ 已阅"},
            "type": "primary", "value": {"action": "mark_read", "id": email_id},
        }],
    })

    return {"header": header, "elements": elements}


def build_edit_draft_card(email_id: str, current_draft: str, email_data: dict, classification: dict) -> dict:
    """Build a card with an editable draft text area."""
    subject = email_data.get("subject", "No Subject")
    subject = re.sub(r"^(Subject|主题)[:：]\s*", "", subject, flags=re.IGNORECASE).strip()

    header = {
        "template": "blue",
        "title": {"content": f"✏️ 编辑回复: {subject}", "tag": "plain_text"},
    }

    elements: list[dict] = [
        {
            "tag": "form",
            "name": "Form_draft",
            "elements": [
                {
                    "tag": "input",
                    "name": "draft_input",
                    "input_type": "multiline_text",
                    "rows": 6,
                    "placeholder": {"tag": "plain_text", "content": "请输入回复内容"},
                    "default_value": current_draft or "",
                    "width": "fill",
                    "label": {"tag": "plain_text", "content": "📝 回复正文:"},
                    "label_position": "top",
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "default",
                    "columns": [
                        {
                            "tag": "column", "width": "auto", "vertical_align": "top",
                            "elements": [{
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "✓ 保存并返回"},
                                "type": "primary",
                                "action_type": "form_submit",
                                "name": "Button_submit",
                                "value": {"action": "save_draft", "id": email_id},
                            }],
                        },
                        {
                            "tag": "column", "width": "auto", "vertical_align": "top",
                            "elements": [{
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "✕ 取消"},
                                "type": "default",
                                "value": {"action": "cancel_edit", "id": email_id},
                                "name": "Button_cancel",
                            }],
                        },
                    ],
                },
            ],
        }
    ]

    return {"header": header, "elements": elements}


def build_processed_card(status_text: str, subject: str = "") -> dict:
    """Build a collapsed card showing the email has been processed."""
    return {
        "header": {
            "title": {"content": f"{status_text} | {subject}", "tag": "plain_text"},
            "template": "grey",
        },
        "elements": [{
            "tag": "div",
            "text": {"tag": "lark_md", "content": "✅ 已处理完成，无需继续操作。"},
        }],
    }


def _display_name(raw: str) -> str:
    """Extract a display name from raw sender/recipient string."""
    m = re.search(r"name='(.*?)'", raw)
    if m:
        return m.group(1)
    email = extract_email_address(raw)
    if email:
        return email.split("@")[0]
    return raw[:30]


def _body_snippet(body: str, max_len: int = 200) -> str:
    """Extract a text snippet from an email body (strip HTML)."""
    if not body:
        return "无内容摘要"
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text or "无内容摘要"
