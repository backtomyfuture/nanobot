# Exchange Email Processing

You have access to tools for processing Exchange emails. When you receive a message from the `exchange` channel (starting with `[Exchange Email Received]`), follow this workflow:

## Step 1: Check State

Use `email_state_read` with the email ID to check if this email has been processed before. If status is anything other than `not_found`, skip processing unless explicitly asked to reprocess.

## Step 2: Classify

Use `classify_email` with the email's subject, body, and sender. This returns a JSON with:
- `priority`: P0 (urgent) to P3 (low)
- `need_reply`: whether a reply is expected
- `intent`: 咨询 / 审批 / 通知 / 垃圾邮件
- `summary`: one-line summary

Save the classification using `email_state_write` with status `classified`.

## Step 3: Ingest to Knowledge Base

Use `qdrant_ingest` to index the email into the vector database. Provide: email_id, subject, sender, body, and thread_id (if available from the email's conversation_id field).

## Step 4: Decide Action

Based on classification:

- **need_reply = true**: Proceed to Step 5 (retrieve context and draft a reply)
- **priority = P0 or P1, need_reply = false**: Use `message` tool to notify the user on the configured notification channel with a brief summary, then save state as `skipped`
- **intent = 垃圾邮件 or priority = P3**: Save state as `skipped`, no notification needed
- **Otherwise (P2 通知 etc)**: Send a brief notification, save as `skipped`

## Step 5: Retrieve Historical Context

Use `qdrant_search` to find relevant historical emails:
1. If the email has a thread_id/conversation_id, search by thread first
2. Then search semantically using the subject + first 500 chars of body
3. Include the sender filter for more relevant results

Format the search results as context text for the drafter.

## Step 6: Draft Reply

Use `draft_email` with:
- The email's subject, sender, and body
- The context from Step 5 (formatted as text)
- Optional modifier if the routing/classification suggests a special tone

Save the draft using `email_state_write` with status `drafted` and the `draft` field.

## Step 7: Notify for Approval

Send a notification to the user using the `message` tool with the configured notification channel and chat_id. Format the notification as:

```
📧 新邮件需要审批

发件人: {sender}
主题: {subject}
分类: {priority} | {intent}
摘要: {summary}

--- 拟稿回复 ---
{draft}
---

请回复:
• approve {email_id} — 直接发送
• reject {email_id} — 拒绝
• edit {email_id} 新内容... — 修改后发送
```

Update state to `waiting_approval`.

## Step 8: Handle Approval

When the user responds with an approval decision (the message will come from the notification channel, e.g. feishu):

- **starts with "approve"**: Extract the email_id, read its state, use `exchange_reply` to send the saved draft, then update state to `sent`
- **starts with "reject"**: Extract the email_id, update state to `rejected`
- **starts with "edit"**: Extract the email_id and the new content after it, use `exchange_reply` with the new content, update state to `sent`

## Daily Summary

When asked to generate a daily email summary (e.g. via cron task "生成今日邮件处理摘要"), use `email_state_list` to get today's processed emails and produce a summary report:
- Total emails processed
- Breakdown by priority and intent
- List of pending items (status=waiting_approval)
- Any errors

Send the summary to the user via the `message` tool.

## Important Notes

- Always save state after each step to enable recovery from failures
- The email body may be very long; focus on the key content for classification
- When replying, use the language matching the original email
- Never fabricate information in replies; if unsure, ask the user
- Use `qdrant_ingest` for every email to continuously build the knowledge base
- The `message` tool can send to any channel; use the notification channel configured in the exchange settings
