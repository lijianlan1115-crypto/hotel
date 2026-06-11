#!/usr/bin/env bash
set -euo pipefail

# Run from the OpenClaw workspace root on the Alibaba server.
# Replace --session main with the production session id if your gateway uses one.

openclaw cron add \
  --name "S2 hourly operating snapshot" \
  --cron "7 * * * *" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s02-operating-snapshot for hotel_id=puyue. First call runtime snapshot and inspect freshness_status/data_business_date/data_snapshot_time. If freshness_status is not fresh, do not send a today operating report; send a short stale-data notice instead. Keep the task concise and finish within 180 seconds."

openclaw cron add \
  --name "S15 daily sales baseline" \
  --cron "30 7 * * *" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s15-sales-baseline for hotel_id=puyue and today's business date. Persist the baseline and send the daily target summary."

openclaw cron add \
  --name "S16 hourly deviation diagnosis" \
  --cron "12 * * * *" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s16-progress-deviation for hotel_id=puyue. Compare current progress with baseline and send actionable deviations."

openclaw cron add \
  --name "S14 weekly operation diagnosis" \
  --cron "0 9 * * 1" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s14-operation-diagnosis for hotel_id=puyue. Produce the weekly OTA operation diagnosis and top improvement tasks."

openclaw cron list
