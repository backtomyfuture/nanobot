"""Email draft generation tool: uses the configured LLM to compose reply drafts."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

DRAFT_SYSTEM_PROMPT = """你是一个专业的行政助手。
你的任务是根据提供的【历史背景】和【当前邮件】，代用户拟写一封回复邮件。

要求：
1. 参考历史背景中的信息，确保回复的一致性和准确性。
2. 模仿用户的稳重、专业且礼貌的写作风格。
3. 直接输出最终的邮件回复正文。
4. 不要输出思考过程或标签，也不要包含任何解释性文字。
5. 【重要】绝对不要包含原邮件内容、发件人信息或引用历史。系统会自动追加，如果你输出了会导致重复。只输出你的回复部分即可。

请使用与原邮件相同的语言回复。"""


class EmailDrafterTool(Tool):
    """Generate a professional reply draft for an Exchange email using LLM."""

    name = "draft_email"
    description = (
        "Generate a professional reply draft for an email. "
        "Provide the email content and optionally historical context from qdrant_search. "
        "Returns the draft text ready for human review."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Original email subject"},
            "sender": {"type": "string", "description": "Original email sender"},
            "body": {"type": "string", "description": "Original email body"},
            "context": {
                "type": "string",
                "description": (
                    "Historical context from qdrant_search (formatted as text). "
                    "Include relevant prior emails for better draft quality."
                ),
            },
            "modifier": {
                "type": "string",
                "description": (
                    "Optional style/instruction modifier to append to the system prompt. "
                    "E.g. 'use a more formal tone' or 'this is an urgent matter'"
                ),
            },
        },
        "required": ["subject", "sender", "body"],
    }

    def __init__(self, llm_call: Any):
        self._llm_call = llm_call

    async def execute(
        self, subject: str, sender: str, body: str,
        context: str = "", modifier: str = "", **kwargs: Any,
    ) -> str:
        system = DRAFT_SYSTEM_PROMPT
        if modifier:
            system = system + "\n\n" + modifier.strip()

        context_section = context if context else "无相关历史背景"
        truncated_body = body[:4000] if len(body) > 4000 else body

        user_msg = (
            f"【历史背景】:\n{context_section}\n\n"
            f"<email_content>\n"
            f"【当前待回复邮件】:\n"
            f"发件人: {sender}\n"
            f"主题: {subject}\n"
            f"正文:\n{truncated_body}\n"
            f"</email_content>"
        )

        try:
            response = await self._llm_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
            )
            draft = response.strip()
            if not draft:
                return "Error: LLM returned empty draft"
            return draft
        except Exception as e:
            logger.error("Draft generation failed: {}", e)
            return f"Error generating draft: {e}"
