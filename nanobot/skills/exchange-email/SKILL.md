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

## Step 7: Notify for Approval (Interactive Card)

Use `send_approval_card` to send a Feishu interactive card with:
- email_id, draft, subject, sender
- summary, priority, intent, reasoning from classification

The card displays the email summary, draft preview, and interactive buttons (approve/reject/edit/save-draft). Save the returned message_id in the email state for later card updates.

Update state to `waiting_approval`.

For important emails that DON'T need a reply (P0/P1, need_reply=false), use `send_notification_card` instead (read-only card with "mark read" button).

## Step 8: Handle Card Action Callbacks

When you receive a message starting with `[Feishu Card Action]`, it means the user clicked a button on the card. Parse the action_type and email_id from the message.

Handle each action:

- **approve**: Read the email state (get draft), use `exchange_reply` to send it, use `update_feishu_card` to update the card to "已批准" status, update state to `sent`
- **reject**: Use `update_feishu_card` to show "已拒绝", update state to `rejected`
- **mark_read**: Use `update_feishu_card` to show "已阅", update state to `archived`
- **edit_draft**: The form_values contain the new draft text in "draft_input". Save the new draft to email state, then rebuild and send a new approval card with the updated draft
- **save_draft_only**: Read the email state, create an Exchange draft via exchange tools, update card to "已存草稿"
- **cancel_edit**: Rebuild the approval card in view mode (no changes)

## Step 9: Index Sent Reply

After successfully sending a reply or forward (approve action in Step 8), use `qdrant_ingest` to index the sent content:
- email_id: "reply_{original_email_id}"
- subject: "Re: {original_subject}"
- sender: "me"
- body: the draft content that was sent
- thread_id: same as original email (if available)

This ensures future RAG searches find your past replies for style consistency.

## Daily Summary

When asked to generate a daily email summary, refer to the `daily-summary` skill for the full workflow:
1. Use `email_state_list` to get today's records
2. Group by status, priority, and intent
3. Format a structured report
4. Send via `message` tool or `send_notification_card`

## Important Notes

- Always save state after each step to enable recovery from failures
- The email body may be very long; focus on the key content for classification
- When replying, use the language matching the original email
- Never fabricate information in replies; if unsure, ask the user
- Use `qdrant_ingest` for every incoming email AND every sent reply to build the knowledge base
- For card-based notifications, prefer `send_approval_card`/`send_notification_card` over plain text
- The `message` tool can send to any channel; use the notification channel configured in the exchange settings
