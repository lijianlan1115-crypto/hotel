# Feishu Routing Contract

The current S14 report is a unified 23-item diagnosis. It does **not** ask for an
OTA channel. The Feishu conversation asks only for the data source.

## Group Conversation Flow

1. The user sends `@机器人 S14诊断`.
2. The entry service sends an interactive card with two buttons:
   - `数据库`
   - `上传Excel`
3. Database choice runs the current `ota-marketing-diagnosis` project immediately
   with `platform=multi` and the latest 30-day period.
4. Excel choice stores an `awaiting_excel` state keyed by `chat_id + sender_id`.
5. The user sends the Excel attachment as the next group message. The attachment
   message does not need another @ mention.
6. The entry service downloads the file and invokes the same current report engine
   in `diagnose-excel` mode.
7. The state expires after 10 minutes and is cleared after a successful run.

## Required Event Metadata

The text trigger, card-action callback and file-message callback must pass the same:

- `chat_id`
- `sender_id` / sender `open_id`

Example command calls:

```bash
# 1. Initial group trigger
python scripts/s14_feishu_entry.py \
  --text "S14诊断" \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card

# 2A. Database button callback
python scripts/s14_feishu_entry.py \
  --source-choice database \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card

# 2B. Excel button callback
python scripts/s14_feishu_entry.py \
  --source-choice excel \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card

# 3. Next attachment message after Excel was selected
python scripts/s14_feishu_entry.py \
  --excel "/downloaded/S14酒店诊断_中文表头上传模板.xlsx" \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card
```

## Current Report Engine

Both sources call:

```text
/opt/openclaw/workspaces/ota-marketing-diagnosis
```

Database mode:

```text
python -m marketing_diagnosis.main diagnose-db
```

Excel mode:

```text
python -m marketing_diagnosis.main diagnose-excel --excel <path>
```

The environment must provide:

```text
S14_DB_DSN
S14_REPORT_OUTPUT_DIR=/var/lib/ota-marketing-diagnosis/reports
S14_PUBLIC_BASE_URL=http://47.108.200.194:8081/s14-reports
```

Optional overrides:

```text
S14_DIAGNOSIS_PROJECT_ROOT
S14_DIAGNOSIS_PYTHON
S14_SOURCE_STATE_FILE
S14_SOURCE_STATE_TTL_SECONDS
```

## Reply Requirements

Every generated report reply must show one of:

```text
数据来源：数据库
```

or:

```text
数据来源：Excel
```

The report URL must be a real interactive-card button URL. Do not send a cached
report, old Agent summary or old M01-M08 result.

## Data Fixes Used by the Current Engine

- Scan-order detail rows are preserved even when supplied as an independent
  `scan_orders` section and are summarized into item 07.
- Promotion finance strings such as
  `2026-07-08 00:00:00-23:59:59` are filtered using their first ten date
  characters instead of MySQL `DATE(transaction_time)`.
- Promotion transaction type is Unicode-NFKC normalized before matching
  `推广通支出`.

## Forbidden

- Do not ask for 美团 / 携程 / 飞猪 / 多渠道.
- Do not default to `fliggy`.
- Do not use the legacy M01-M08 local runner for the final report.
- Do not accept an unattached Excel file from a different user or group while a
  pending state belongs to someone else.
- Do not reuse cached Agent text, cached JSON, previous Feishu messages or old
  report links.
