# S14 酒店运营诊断示例

## 飞书输入

```text
生成飞猪 OTA 诊断报告，周期 2026-06-01 到 2026-06-10
```

## 数据库模式输入

S14 只接收控制字段，诊断事实数据由 S14 自己从 `hotel_pricing` 的 6 张业务表读取。

```json
{
  "hotel_id": "puyue",
  "hotel_name": "贵阳璞悦·奢电竞酒店",
  "platform": "fliggy",
  "channel_source": "飞猪",
  "channel_mode": "single",
  "data_source_mode": "database",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "output_dir": "./outputs",
  "public_base_url": null,
  "dry_run": true
}
```

## Excel 上传模式输入

Excel 文件只作为受控数据源路径传入。Excel 内部中文字段必须由 `config/excel_field_mapping.yaml` / `references/excel_field_mapping.csv` 映射成标准字段后才能参与计算。

```json
{
  "hotel_id": "puyue",
  "hotel_name": "贵阳璞悦·奢电竞酒店",
  "platform": "fliggy",
  "channel_source": "飞猪",
  "channel_mode": "single",
  "data_source_mode": "excel_upload",
  "input_excel_path": "/path/to/uploaded.xlsx",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "output_dir": "./outputs",
  "public_base_url": null,
  "dry_run": true
}
```

## 禁止输入示例

以下字段会被 `references/input_schema.json` 拒绝：

```json
{
  "hotel_id": "puyue",
  "platform": "fliggy",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "metrics": {"revpar": 120},
  "business_fields": {"payment_conversion_rate": 0.03},
  "upstream_skill_output": {"skill_id": "s02-operating-snapshot"}
}
```

## runtime 输出样例

```json
{
  "status": "ok",
  "skill_id": "s14-operation-diagnosis",
  "platform": "fliggy",
  "channel_source": "飞猪",
  "channel_mode": "single",
  "data_source": "hotel_pricing_tables",
  "raw_score": 72,
  "final_score": 68,
  "risk_level": "medium",
  "report_url": "file:///outputs/ota_diagnosis_report_demo.html",
  "feishu_message": "【S14 酒店 OTA 诊断报告已生成】..."
}
```
