# Daily Email Summary

When asked to generate a daily email summary (e.g. "生成今日邮件摘要", "daily email report", or triggered by a cron job), follow this workflow:

## Step 1: Gather Data

Use `email_state_list` to retrieve today's email processing records. If no status filter is specified, get all records (limit 100).

## Step 2: Categorize

Group the emails by status and classification:

- **Processed**: sent, forwarded, archived
- **Pending**: waiting_approval, drafted
- **Skipped**: skipped (low priority / spam)
- **Errors**: error

Also group by priority (P0-P3) and intent.

## Step 3: Build Report

Compose a structured summary in the following format:

```
📊 邮件日报 — {date}

📬 总计处理: {total} 封
├ ✅ 已回复/转发: {sent_count}
├ ⏳ 待审批: {pending_count}
├ ⏭️ 已跳过: {skipped_count}
└ ❌ 异常: {error_count}

📌 优先级分布:
├ 🔴 P0 紧急: {p0_count}
├ 🟠 P1 重要: {p1_count}
├ 🟡 P2 一般: {p2_count}
└ ⚪ P3 低优: {p3_count}

⏳ 待处理项:
{list of pending emails with subject and sender}

❌ 异常项:
{list of error emails with subject and error_message}
```

## Step 4: Send Report

Use the `message` tool to send the summary to the user via the configured notification channel (typically feishu).

Or if `send_notification_card` is available, send it as a Feishu card for better formatting.

## Cron Setup

To schedule this as a daily task, add a cron job via nanobot CLI:

```bash
nanobot cron add --name "daily_email_summary" \
  --message "请生成今日邮件处理摘要" \
  --cron "0 18 * * *" \
  --deliver --channel feishu
```

This will trigger the agent at 6 PM daily to generate and deliver the summary.
