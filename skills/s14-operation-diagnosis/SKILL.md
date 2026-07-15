---
name: s14-operation-diagnosis
description: "S14酒店OTA整体诊断。触发后先选择数据库或上传Excel，统一生成当前23项HTML报告，不再区分渠道。"
---

# S14 酒店 OTA 整体诊断

## 当前唯一生产规则

本 Skill 的生产报告必须调用：

```text
/opt/openclaw/workspaces/ota-marketing-diagnosis
```

并使用该项目当前的23项取数、评分和HTML渲染链路。

禁止继续使用旧版：

```text
M01-M08
runtime/calculator.py
s14_local_report.py
飞猪单渠道默认值
旧版OTA诊断摘要
```

## 飞书触发流程

用户在群里发送：

```text
@机器人 S14诊断
```

机器人只询问数据来源：

```text
数据库 / 上传Excel
```

不得询问：

```text
美团 / 携程 / 飞猪 / 去哪儿 / 多渠道
```

当前统一设置：

```text
platform = multi
channel_source = 整体诊断
```

### 选择数据库

立即调用：

```bash
python -m marketing_diagnosis.main diagnose-db \
  --dsn-env S14_DB_DSN \
  --hotel-id puyue \
  --hotel-name "璞悦·奢电竞酒店(贵阳花溪公园店)" \
  --platform multi \
  --output "$S14_REPORT_OUTPUT_DIR"
```

默认周期为最近30天。

### 选择上传Excel

机器人回复：

```text
数据来源：Excel
请直接发送Excel附件，无需再次@机器人。
```

入口服务按以下组合记录10分钟等待状态：

```text
chat_id + sender_id
```

用户下一条直接发送 `.xlsx` 或 `.xlsm`，入口服务下载文件后调用：

```bash
python -m marketing_diagnosis.main diagnose-excel \
  --excel "/downloaded/file.xlsx" \
  --platform multi \
  --output "$S14_REPORT_OUTPUT_DIR"
```

附件消息不需要再次@，但必须与选择上传Excel时的群聊和用户一致。

## OpenClaw Python入口

兼容调用方式仍为：

```python
from runtime import S14OperationDiagnosis

result = S14OperationDiagnosis(config).execute(inputs)
```

允许的数据来源：

```text
data_source_mode = database
data_source_mode = excel_upload
```

无论哪种模式，`runtime/__init__.py` 都必须桥接当前 `ota-marketing-diagnosis` 项目，不得在本 Skill 内重新计算旧模块分。

## 输入示例

数据库：

```json
{
  "hotel_id": "puyue",
  "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
  "platform": "multi",
  "period_start": "2026-06-16",
  "period_end": "2026-07-15",
  "data_source_mode": "database",
  "output_dir": "/var/lib/ota-marketing-diagnosis/reports",
  "public_base_url": "http://47.108.200.194:8081/s14-reports"
}
```

Excel：

```json
{
  "hotel_id": "puyue",
  "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
  "platform": "multi",
  "data_source_mode": "excel_upload",
  "input_excel_path": "/downloaded/S14酒店诊断_中文表头上传模板.xlsx",
  "output_dir": "/var/lib/ota-marketing-diagnosis/reports",
  "public_base_url": "http://47.108.200.194:8081/s14-reports"
}
```

## 飞书入口命令

首次触发：

```bash
python scripts/s14_feishu_entry.py \
  --text "S14诊断" \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card
```

数据库按钮回调：

```bash
python scripts/s14_feishu_entry.py \
  --source-choice database \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card
```

Excel按钮回调：

```bash
python scripts/s14_feishu_entry.py \
  --source-choice excel \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card
```

后续附件：

```bash
python scripts/s14_feishu_entry.py \
  --excel "/downloaded/file.xlsx" \
  --chat-id "$CHAT_ID" \
  --sender-id "$SENDER_ID" \
  --format card
```

## 数据修复要求

### 07 扫码订单

数据源：

```text
hotel_puyue.meituan_ota_scan_order_detail
```

若加载器输出独立 `scan_orders` section，归一化阶段必须保留该section，并生成：

```text
period_type = scan_order_summary
scan_order_count = COUNT(*) 或明细行数量
```

不得因为 `scan_orders` 不在旧 `SECTIONS` 列表中而丢失。

### 09 推广投入

数据源：

```text
hotel_puyue.meituan_ota_promotion_finance_detail
```

`transaction_time` 可能为：

```text
2026-07-08 00:00:00-23:59:59
```

日期过滤必须使用字符串前10位：

```sql
LEFT(CAST(transaction_time AS CHAR), 10)
```

不得使用：

```sql
DATE(transaction_time)
```

交易类型必须先进行 Unicode NFKC 归一化，再匹配：

```text
推广通支出
```

金额按绝对值求和：

```text
SUM(ABS(transaction_amount))
```

## 返回要求

飞书结果必须明确标注：

```text
数据来源：数据库
```

或：

```text
数据来源：Excel
```

必须返回本次新生成的23项HTML链接，不得复用旧链接或旧Agent文字。

## 环境变量

```text
S14_DB_DSN
S14_REPORT_OUTPUT_DIR=/var/lib/ota-marketing-diagnosis/reports
S14_PUBLIC_BASE_URL=http://47.108.200.194:8081/s14-reports
S14_DIAGNOSIS_PROJECT_ROOT=/opt/openclaw/workspaces/ota-marketing-diagnosis
S14_SOURCE_STATE_FILE=/var/lib/hotel-ota-ai/s14-source-state.json
S14_SOURCE_STATE_TTL_SECONDS=600
```

## 禁止事项

- 不得询问渠道。
- 不得默认飞猪。
- 不得运行旧M01-M08评分。
- 不得把扫码订单已加载数据丢弃。
- 不得用 `DATE(transaction_time)` 过滤异常时间字符串。
- 不得让其他群或其他用户的附件命中当前等待状态。
- 不得使用缓存报告、旧摘要或历史链接。
