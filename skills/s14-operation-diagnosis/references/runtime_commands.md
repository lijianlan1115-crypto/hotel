# S14 runtime commands

S14 在 OpenClaw 中必须独立运行，不依赖任何其他 Skill 输出作为输入。

## 当前本地验证入口

当前阶段先不读取服务器数据库，也不读取其他 Skill 输出。直接读取本地测试文件夹、飞猪 OTA 已获取数据整理表和模拟飞书表单。

```bash
python3 -B openclaw-s14-operation-diagnosis-skill/scripts/s14_local_report.py
```

默认输入：

| 类型 | 路径 |
|---|---|
| 规则工作簿 | `/Users/jelly/Desktop/work/酒店数字员工/酒店OTA全面诊断系统_开发交付总文档_v2_精简版.xlsx` |
| PMS 测试数据文件夹 | `/Users/jelly/Downloads/2026.6.9测试数据` |
| 飞猪 OTA 已获取数据 | `/Users/jelly/Desktop/work/酒店数字员工/飞猪OTA已获取数据整理表.xlsx` |
| 模拟飞书表单 | `openclaw-s14-operation-diagnosis-skill/inputs/s14_manual_form_mock.csv` |

默认输出：

| 类型 | 路径 |
|---|---|
| HTML 客户报告 | `/Users/jelly/Desktop/work/酒店数字员工/ota_diagnosis_report_demo.html` |
| file 链接 | `file:///Users/jelly/Desktop/work/%E9%85%92%E5%BA%97%E6%95%B0%E5%AD%97%E5%91%98%E5%B7%A5/ota_diagnosis_report_demo.html` |
| JSON 结果 | `openclaw-s14-operation-diagnosis-skill/outputs/s14_local_report/s14_result.json` |

后续替换说明：

- `TODO(server-db)`：把本地 PMS 文件夹和飞猪 OTA Excel 替换为服务器数据库表，表内必须保留日度、月度、房型、平台/渠道维度历史数据。
- `TODO(feishu-form)`：把 `inputs/s14_manual_form_mock.csv` 替换为飞书表单或多维表格记录链接/API。

## 后续 OpenClaw 正式数据来源

生产阶段只允许两种受控数据来源：

1. `database`：从 `hotel_pricing` 的 6 张业务表读取。
2. `excel_upload`：从 `input_excel_path` 指向的 `.xlsx/.xlsm` 读取，并按 `config/excel_field_mapping.yaml` 映射中文字段。

## OpenClaw 正式入口

```python
from runtime import S14OperationDiagnosis

result = S14OperationDiagnosis({
    "db_kind": "mysql",
    "db_dsn": "mysql://user:password@host:3306/hotel_pricing",
    "report_output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
    "public_base_url": "http://47.108.200.194:8088/s14-reports"
}).execute({
    "hotel_id": "puyue",
    "platform": "fliggy",
    "period_start": "2026-06-01",
    "period_end": "2026-06-10",
    "data_source_mode": "database",
    "dry_run": True
})
```

Excel 上传模式：

```python
result = S14OperationDiagnosis({
    "report_output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
    "public_base_url": "http://47.108.200.194:8088/s14-reports"
}).execute({
    "hotel_id": "puyue",
    "platform": "fliggy",
    "period_start": "2026-06-01",
    "period_end": "2026-06-10",
    "data_source_mode": "excel_upload",
    "input_excel_path": "/path/to/uploaded.xlsx",
    "dry_run": True
})
```

## 禁止

- 禁止传入 `metrics`
- 禁止传入 `business_fields`
- 禁止传入 `json_payload`
- 禁止传入 `manual_diagnosis_input`
- 禁止传入任何上游 Skill 输出
- 禁止把 CSV 当正式上传数据源

## OpenClaw 部署文件

- `openclaw.skill.yaml`：部署清单
- `references/input_schema.json`：输入白名单
- `references/output_schema.json`：输出结构
- `config/fields.yaml`：字段、权重、公式参数、数据来源策略
- `config/excel_field_mapping.yaml`：Excel 中文字段映射规则
- `config/hotel_pricing_sources.yaml`：hotel_pricing 业务表字段映射规则
- `references/excel_field_mapping.csv`：Excel 字段映射表
- `references/excel_field_mapping.xlsx`：Excel 字段映射表
- `config/database_schema.sql`：S14 兼容归一化表契约
- `runtime/__init__.py`：OpenClaw Python 入口
- `runtime/data_fetcher.py`：数据库/Excel 读取层
- `runtime/calculator.py`：计算公式唯一实现

## 测试

```bash
python3 -B openclaw-s14-operation-diagnosis-skill/scripts/s14_local_report.py
python3 -B tests/smoke_test.py
python3 -B tests/excel_smoke_test.py
```
