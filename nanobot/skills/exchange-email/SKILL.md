# Exchange Email Processing

When you receive a message from the `exchange` channel (starting with `[Exchange Email Received]`), follow this workflow. All tools prefixed with `mcp_exchange_` are provided by the Exchange MCP server.

## Step 1: Check State

Use `mcp_exchange-tools_email_state_read` with the email ID. If status is not `not_found`, skip unless asked to reprocess.

## Step 2: Classify (Agent Direct — no tool needed)

Analyze the email and produce a classification. Output a JSON block in your reasoning:

```json
{"priority": "P0|P1|P2|P3", "need_reply": true/false, "intent": "咨询|审批|通知|垃圾邮件", "summary": "一句话摘要", "reasoning": "分类理由"}
```

Priority definitions:
- **P0**: Urgent and important — senior leadership, urgent approvals
- **P1**: Important, reply within the day — business emails requiring response
- **P2**: Routine — general communication, information sync
- **P3**: Low priority — notifications, ads, automated emails

Save using `mcp_exchange-tools_email_state_write` with status `classified` and the classification object.

## Step 3: Ingest to Knowledge Base

Use `mcp_exchange-tools_qdrant_ingest` to index the email (email_id, subject, sender, body, thread_id if available).

## Step 4: Decide Action

Based on your classification:

- **need_reply = true**: Go to Step 5
- **P0/P1, need_reply = false**: Send notification card (Step 7b), save as `skipped`
- **垃圾邮件 or P3**: Save as `skipped`, no notification
- **Otherwise**: Brief notification via `message` tool, save as `skipped`

## Step 5: Retrieve Context

Use `mcp_exchange-tools_qdrant_search` to find relevant historical emails:
- Search by thread_id if available
- Then semantic search using subject + body excerpt
- Include sender filter for relevance

## Step 6: Draft Reply (Agent Direct — no tool needed)

Compose a professional reply draft based on:
- The original email content
- Historical context from Step 5
- The sender's language (match it)

Guidelines:
- Address the sender's questions/requests directly
- Professional, courteous tone
- Concise but complete
- Do NOT include the original email or sender info (system appends it)
- Do NOT include explanations or thinking — only the reply body

Save draft via `mcp_exchange-tools_email_state_write` with status `drafted` and the `draft` field.

## Step 7a: Send Approval Card

Use `mcp_exchange-tools_send_approval_card` with: email_id, draft, subject, sender, summary, priority, intent, reasoning.

Save the returned `message_id` via `mcp_exchange-tools_email_state_write` (add `message_id` field). Set status to `waiting_approval`.

## Step 7b: Send Notification Card (read-only)

For important emails that don't need reply, use `mcp_exchange-tools_send_notification_card` with: email_id, subject, sender, summary, priority, reasoning.

## Step 8: Handle Card Actions

When you receive `[Feishu Card Action]`, parse action_type and email_id:

- **approve**: Read state (get draft + message_id), call `mcp_exchange-tools_exchange_reply` with the draft, then `mcp_exchange-tools_update_feishu_card` to show "已批准", update state to `sent`. Also ingest the sent reply via `mcp_exchange-tools_qdrant_ingest` (sender="me", subject="Re: ...").
- **reject**: Update card to "已拒绝", state to `rejected`
- **mark_read**: Update card to "已阅", state to `archived`
- **edit_draft**: Extract new text from form_values.draft_input, save to state, send a new approval card with updated draft
- **save_draft_only**: Update card to "已存草稿", state to `draft_saved`

## Daily Summary

When asked to generate a daily email summary, refer to the `daily-summary` skill.

## Notes

- Save state after each step for failure recovery
- Match the original email's language in replies
- Never fabricate information; ask the user if unsure
- Ingest every incoming email AND every sent reply to build the knowledge base
- Prefer card tools (`send_approval_card`/`send_notification_card`) over plain text for notifications
