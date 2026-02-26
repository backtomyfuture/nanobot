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

## Step 3: Decide Action

Based on classification:

- **need_reply = true**: Proceed to Step 4 (draft a reply)
- **priority = P0 or P1, need_reply = false**: Notify the user with a summary via the configured notification channel, then save state as `skipped`
- **intent = 垃圾邮件 or priority = P3**: Save state as `skipped`, no notification needed
- **Otherwise**: Send a brief notification, save as `skipped`

## Step 4: Draft Reply

When a reply is needed, compose a professional reply draft in the same language as the original email. Consider:
- Address the sender's questions or requests directly
- Maintain a professional and courteous tone
- Keep it concise but complete
- Do NOT include the original email content (the system appends it automatically)

Save the draft using `email_state_write` with status `drafted` and the `draft` field.

## Step 5: Notify for Approval

Send a message to the user (via the notification channel) containing:
1. Email summary (sender, subject, classification)
2. The draft reply
3. Ask the user to respond with one of:
   - `approve [email_id]` - send the draft as-is
   - `reject [email_id]` - discard the draft
   - `edit [email_id] <new content>` - replace the draft with new content

Update state to `waiting_approval`.

## Step 6: Handle Approval

When the user responds with an approval decision:

- **approve**: Use `exchange_reply` to send the email, then update state to `sent`
- **reject**: Update state to `rejected`
- **edit**: Update the draft in state, then send using `exchange_reply`, update state to `sent`

## Daily Summary

When asked to generate a daily email summary, use `email_state_list` to get today's processed emails and produce a summary report with:
- Total emails processed
- Breakdown by priority and intent
- List of pending items (waiting_approval)
- Any errors

## Important Notes

- Always save state after each step to enable recovery from failures
- The email body may be very long; focus on the key content for classification
- When replying, use the language matching the original email
- Never fabricate information in replies; if unsure, ask the user
