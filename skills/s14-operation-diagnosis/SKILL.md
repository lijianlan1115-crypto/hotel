---
name: s14-operation-diagnosis
description: "独立 S14 酒店 OTA 全面诊断报告 Skill。触发语可由飞书 Bot 或 OpenClaw Agent 识别：S14诊断、运营诊断、OTA全面诊断、生成诊断报告、飞猪诊断、美团诊断、携程诊断、多渠道诊断。"
---

# S14 酒店 OTA 全面诊断报告

## 定位

本 Skill 是 **S14 OTA 经营诊断能力包**，只负责查数据库、计算评分、生成 HTML 报告和返回结构化结果。

它不负责监听飞书消息，也不负责关键词判断。飞书 Bot 或 OpenClaw Agent 负责接收消息、识别触发词，然后调用：

```python
S14OperationDiagnosis(config).execute(inputs)
```

## 运行链路

```text
飞书用户
↓
飞书 Bot / OpenClaw Agent
↓
识别 “运营诊断 / S14诊断 / OTA全面诊断”
↓
调用 S14OperationDiagnosis.execute(inputs)
↓
runtime/data_fetcher.py 从 MySQL/SQLite 读取 hotel_pricing 业务表
↓
runtime/calculator.py 计算 M01-M08 模块分、总分和封顶规则
↓
runtime/__init__.py 生成 ota_diagnosis_report_demo.html
↓
飞书 Bot / Agent 返回 report_url
```

## 核心原则

- S14 必须独立运行，不依赖任何其他 Skill 输出。
- OpenClaw/飞书 Bot 只能传控制字段，不得传诊断事实数据。
- 当前本地验证阶段不读服务器数据库、不读取其他 Skill 输出，直接读取本 Skill 指定的本地 PMS 文件夹、飞猪 OTA 已获取数据整理表和模拟飞书表单。
- 生产阶段经营、OTA、推广、口碑、页面人工项等事实数据必须由 `runtime/data_fetcher.py` 从受控数据源读取：数据库 `hotel_pricing` 的 6 张业务表或上传 Excel。
- 输入字段必须通过 `references/input_schema.json` 校验。
- 输出字段必须符合 `references/output_schema.json`。
- 所有计算公式只允许写在 `runtime/calculator.py`。
- 所有规则、计算、判断必须按“严格执行步骤”运行，不允许飞书 Bot 或模型跳步、改公式、临时判断。
- 字段、模块权重、公式参数和数据策略统一记录在 `config/fields.yaml`。
- Skill 只做诊断和报告，禁止执行真实调价、改房量、开启推广、回复评价等写动作。

## 当前本地验证模式

当前要验证 S14 能力时，先不接数据库，也不接其他智能体或其他 Skill 输出。必须使用下面 4 类输入：

| 输入类别 | 当前路径 | 用途 | 后续替换点 |
|---|---|---|---|
| 规则与评审标准 | `/Users/jelly/Desktop/work/酒店数字员工/酒店OTA全面诊断系统_开发交付总文档_v2_精简版.xlsx` | 读取 `02_模块权重`、`03_主评分规则`、`04_校准与效果校验`、`05_历史纵向分析`、`07_报告展示案例`、`08_前端组件说明`，作为评分、封顶、报告结构依据 | 不替换，作为规则配置源；如客户更新规则表，则替换该文件 |
| PMS/经营测试数据 | `/Users/jelly/Downloads/2026.6.9测试数据` | 读取经营月报、订单、房态、房费等本地表格，用于 RevPAR、ADR、出租率、收入、房型表现、渠道经营分布 | `TODO(server-db)`：替换为服务器数据库日度/月度/房型/平台维度表 |
| 飞猪 OTA 已获取数据 | `/Users/jelly/Desktop/work/酒店数字员工/飞猪OTA已获取数据整理表.xlsx` | 读取飞猪首页、经营数据、同行流失、流失去向、房价房量、订单汇总、推广评价、字段缺口 | `TODO(server-db)`：替换为 OTA 采集入库表，字段必须带 `platform/channel_source` |
| 模拟飞书表单 | `inputs/s14_manual_form_mock.csv` | 读取客户人工必填项：酒店、周期、渠道、竞对、目标、重点房型、页面质量、异常复盘、任务负责人、授权 | `TODO(feishu-form)`：替换为飞书表单或多维表格记录链接/API |

本地验证命令：

```bash
python3 -B openclaw-s14-operation-diagnosis-skill/scripts/s14_local_report.py
```

本地验证输出：

| 输出 | 固定位置 | 要求 |
|---|---|---|
| 客户网页报告 | `/Users/jelly/Desktop/work/酒店数字员工/ota_diagnosis_report_demo.html` | 必须沿用现有网页结构，只更新运行后的数据、规则说明、模块分、缺失项、整改任务 |
| 客户网页链接 | `file:///Users/jelly/Desktop/work/%E9%85%92%E5%BA%97%E6%95%B0%E5%AD%97%E5%91%98%E5%B7%A5/ota_diagnosis_report_demo.html` | 返回给客户或飞书消息 |
| 结构化结果 | `outputs/s14_local_report/s14_result.json` | 给自动化链路校验，包含总分、模块分、封顶规则、字段完整度、缺失字段和报告链接 |

本地验证模式的算法约束：

- 模块权重必须从规则工作簿 `02_模块权重` 读取，M01-M08 权重合计必须为 100。
- 主评分项必须从 `03_主评分规则` 读取，按 `rule_id`、`module_id`、`分值`、`主要字段`、`评分校准方式`、`防失真规则` 逐条计算。
- 总分先按模块内规则得分汇总，再按模块权重加权。
- 封顶规则必须读取 `04_校准与效果校验`，当前重点执行 C01-C07：经营落后、收入连续下滑、订单/转化短板、曝光高但转化低、推广 ROI 低、关键字段缺失、基础项高但核心模块低。
- 历史分析必须读取 `05_历史纵向分析` 约定，保留日度、月度、房型维度、平台维度口径；本地验证阶段至少使用月度和房型维度，缺失日度/平台历史时必须进入缺失字段和可信度提示，不允许编造。
- 渠道必须显式记录，本次为 `platform=fliggy`、`channel_source=飞猪`；后续增加美团、携程、去哪儿、抖音时，所有事实数据必须按渠道过滤后再评分。
- 报告结构必须参考 `07_报告展示案例` 和 `08_前端组件说明`，不能只输出纯 JSON 或纯表格。

## 严格执行步骤

S14 每次执行必须按下面顺序运行，顺序不可调整：

| 步骤 | 代码文件 | 强制要求 |
|---|---|---|
| S01_VALIDATE_INPUT | `runtime/models.py` | 只校验控制输入，拒绝 `metrics/business_fields/json_payload/manual_diagnosis_input/upstream_skill_output` |
| S02_FETCH_SOURCE | `runtime/data_fetcher.py` | 根据 `hotel_id/platform/period_start/period_end` 从数据库或上传 Excel 聚合事实数据 |
| S03_NORMALIZE_FIELDS | `runtime/__init__.py` | 补齐默认字段、计算字段完整度，不编造缺失事实 |
| S04_CALCULATE_MODULES | `runtime/calculator.py` | 固定按 M01 到 M08 顺序计算模块分 |
| S05_APPLY_CAP_RULES | `runtime/calculator.py` | 在模块原始分之后统一应用封顶规则 |
| S06_RENDER_REPORT | `runtime/__init__.py` | 使用模板生成 HTML 报告，返回 `report_url` |
| S07_VALIDATE_OUTPUT | `runtime/__init__.py` | 返回前校验 M01-M08 全覆盖、权重合计100、飞书格式、报告链接 |

输出中必须包含：

- `formula_source: "runtime/calculator.py"`
- `data_source: "local_table_mode"`、`"hotel_pricing_tables"` 或 `"excel_upload"`；旧兼容归一化表才返回 `"s14_operating_metrics"`
- `execution_steps`
- `calculated_fields`
- `mapped_fields`
- `field_contract_file: "references/excel_field_mapping.xlsx"`
- `field_mapping_source: "config/excel_field_mapping.yaml"`
- `feishu_message`

飞书 Bot 只能展示摘要和链接，不能替代 Skill 做评分判断。

## 文件职责

| 文件 | 职责 |
|---|---|
| `openclaw.skill.yaml` | OpenClaw 部署清单，声明入口、schema、配置和安全策略 |
| `config/triggers.yaml` | 触发词、渠道别名、飞书路由和回复策略 |
| `references/input_schema.json` | 输入白名单，只允许控制字段 |
| `references/output_schema.json` | 输出结构约束 |
| `references/feishu_routing.md` | 飞书入口或 OpenClaw Agent 如何按 Skill 配置路由 |
| `config/fields.yaml` | 字段、权重、公式参数、数据来源策略 |
| `config/database_schema.sql` | S14 兼容归一化表结构 |
| `config/hotel_pricing_sources.yaml` | 生产库 `hotel_pricing` 的 6 张业务表读取和字段映射规则 |
| `runtime/__init__.py` | Skill Python 入口 |
| `runtime/data_fetcher.py` | 数据库/Excel 读取、中文字段映射和周期聚合 |
| `runtime/calculator.py` | M01-M08 评分公式和封顶规则 |
| `runtime/models.py` | 输入输出模型 |
| `runtime/router.py` | 可选轻量路由工具，只读触发配置并生成控制输入，不做业务计算 |
| `config/excel_field_mapping.yaml` | Excel 中文字段到标准业务字段的映射规则 |
| `references/excel_field_mapping.csv` | 给用户/客户看的 Excel 字段映射表 |
| `templates/ota_diagnosis_report_demo.template.html` | HTML 报告样式模板 |

## 输入契约

OpenClaw / 飞书 Bot 调用本 Skill 时只允许传控制字段，以及 Excel 模式下的上传文件路径：

```json
{
  "hotel_id": "puyue",
  "platform": "fliggy",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "data_source_mode": "database",
  "input_excel_path": null,
  "hotel_name": "贵阳璞悦·奢电竞酒店",
  "channel_source": "飞猪",
  "image_quality_rating": "unknown",
  "owner_user_id": "ou_xxx",
  "output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports",
  "dry_run": true
}
```

必填字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `hotel_id` | string | 酒店 ID，用于数据库查询 |
| `platform` | enum | `fliggy`、`meituan`、`ctrip`、`qunar`、`douyin`、`multi` |
| `period_start` | date | 诊断开始日期 |
| `period_end` | date | 诊断结束日期 |
OpenClaw_123456

禁止输入：

- `metrics`
- `business_fields`
- `json_payload`
- `manual_diagnosis_input`
- `upstream_skill_output`
- 任何 `s02/s08/s12` 等其他 Skill 输出
- 直接传 Excel 里的业务值，例如 `revpar`、`adr`、`occupancy`

Excel 上传模式允许传：

```json
{
  "hotel_id": "puyue",
  "platform": "fliggy",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "data_source_mode": "excel_upload",
  "input_excel_path": "/path/to/uploaded.xlsx",
  "output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports",
  "dry_run": true
}
```

Excel 里的中文字段必须能在 `config/excel_field_mapping.yaml` 或 `references/excel_field_mapping.csv` 中找到别名。找不到的字段不会进入公式，会进入缺失字段/可信度逻辑。

渠道规则：

- Excel 必须能区分渠道，字段为 `platform` 或 `channel_source`，中文表头可写 `诊断渠道`、`渠道`、`平台`、`OTA渠道`、`渠道来源`。
- 单渠道文件如果没有渠道列，则整份文件按输入参数 `platform` 处理。
- 多渠道文件必须每行提供渠道字段，禁止把飞猪、美团、携程等数据混在一起无渠道标识。
- 所有经营、流量、转化、推广、口碑字段都按渠道过滤后再计算。

## 配置契约

<!-- SQLite 测试：

```json
{
  "db_kind": "sqlite",
  "db_dsn": "/path/to/s14.sqlite"
}
``` -->

MySQL 生产：

```json
{
  "db_kind": "mysql",
  "db_dsn": "mysql://openclaw_user:OpenClaw_123456@47.108.200.194:3306/hotel_pricing",
  "report_output_dir": "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports"
}
```

数据库模式缺少 `db_dsn` 时必须失败。Excel 上传模式缺少 `input_excel_path` 时必须失败。两种模式都不允许降级为手工字段或上游 Skill 输出。

飞书生产测试必须配置 `report_output_dir` 和 `public_base_url`。Skill 只负责把 HTML 写入 `report_output_dir` 并返回 `public_base_url/ota_diagnosis_report_demo.html`，不负责启动或打开 HTTP 端口。网页服务应由 Nginx 或 systemd 常驻托管。

## 数据库契约

数据库模式读取生产库：

```text
hotel_pricing
```

必须读取的业务表：

| 表名 | 用途 |
|---|---|
| `jd01_bookings` | 订单、收入、间夜、取消/流失 |
| `jd04_extensions` | 页面人工项、整改动作、复盘原因 |
| `fact_daily_metrics` | 日度经营、流量、转化、推广、口碑指标 |
| `fact_monthly_metrics` | 月度经营、流量、转化、推广、口碑指标 |
| `fact_room_fee_daily` | 日度房费、价格完整度 |
| `fact_room_status_snapshot` | 房态库存、可售间夜、房型健康度 |

字段映射参考：

```text
config/hotel_pricing_sources.yaml
```

旧兼容归一化表参考：

```text
config/database_schema.sql
```

诊断周期内的数据由 `runtime/data_fetcher.py` 聚合。数据库必须使用 `hotel_id`、`platform/channel`、日期字段过滤，不能由 OpenClaw 或飞书直接传业务指标。

核心口径：

| 字段 | 聚合方式 |
|---|---|
| `revpar` | 平均值 |
| `adr` | 平均值 |
| `occupancy` | 平均值 |
| `room_revenue` | 求和 |
| `sold_room_nights` | 求和 |
| `available_room_nights` | 求和 |
| `exposure` | 求和 |
| `views` | 求和 |
| `booking_conversion_rate` | 平均值 |
| `payment_conversion_rate` | 平均值 |
| `lost_orders` | 求和 |
| `lost_amount` | 求和 |
| `promo_amount` | 求和 |
| `promo_cost` | 求和 |
| `promo_roi` | 优先用 `sum(promo_amount) / sum(promo_cost)` |
| `rating_total` | 平均值 |
| `bad_review_rate` | 平均值 |
| `unreplied_reviews` | 求和 |
| `field_completeness` | 平均值；为空时由 runtime 根据缺失字段计算 |

## Excel 字段映射

Excel 上传模式只读取 `.xlsx/.xlsm`，支持两种结构：

1. 表头表格：第一行或前几行为中文表头，后续每行是日度/周期数据。
2. 键值表：两列结构，第一列字段名，第二列字段值。

中文字段会先映射为标准字段，再进入同一套计算公式。映射文件：

```text
config/excel_field_mapping.yaml
references/excel_field_mapping.csv
```

示例：

| Excel 中文字段 | 标准字段 | 进入模块 |
|---|---|---|
| `渠道` / `平台` / `OTA渠道` | `platform` | 渠道过滤 |
| `日期` / `营业日期` / `业务日期` | `data_date` | 时间过滤 |
| `时间粒度` / `统计粒度` | `time_grain` | 日/周/月/诊断周期 |
| `开始日期` / `周期开始` | `period_start_field` | 周/月/自定义周期过滤 |
| `结束日期` / `周期结束` | `period_end_field` | 周/月/自定义周期过滤 |
| `平均房价` | `adr` | M01 |
| `出租率` | `occupancy` | M01 |
| `曝光量` | `exposure` | M02 |
| `浏览量` | `views` | M02 |
| `浏览-支付转化` | `payment_conversion_rate` | M03 |
| `推广花费` | `promo_cost` | M05 |
| `平台评分` | `rating_total` | M07 |

时间段规则：

- 日度数据：每行填 `日期`，例如 `2026-06-01`。
- 周/月数据：每行建议填 `开始日期`、`结束日期` 和 `时间粒度`。
- 诊断周期数据：可以只填一行周期汇总，但必须和输入的 `period_start/period_end` 对齐。
- 同一个 Excel 可以包含多个时间段，runtime 会先按输入周期过滤，再按字段表中的聚合方式计算。
- `出租率`、`ADR`、`RevPAR`、转化率、评分等比例/均值字段按平均值聚合。
- 曝光、浏览、收入、推广花费等规模字段按求和聚合。

## 评分算法

8 个模块总分 100 分：

| 模块 | 权重 | 计算文件 |
|---|---:|---|
| M01 经营结果与收益锚点 | 20 | `runtime/calculator.py::_calculate_m01` |
| M02 流量曝光与竞争圈 | 15 | `runtime/calculator.py::_calculate_m02` |
| M03 转化下单与路径断点 | 15 | `runtime/calculator.py::_calculate_m03` |
| M04 价格收益与房态库存 | 15 | `runtime/calculator.py::_calculate_m04` |
| M05 推广效率与 ROI | 10 | `runtime/calculator.py::_calculate_m05` |
| M06 页面展示与入口基础 | 10 | `runtime/calculator.py::_calculate_m06` |
| M07 口碑信任与服务响应 | 8 | `runtime/calculator.py::_calculate_m07` |
| M08 执行复盘与数据完整度 | 7 | `runtime/calculator.py::_calculate_m08` |

封顶规则由 `runtime/calculator.py::apply_cap_rules` 执行。

## 输出契约

返回结构必须包含：

```json
{
  "status": "ok|partial|failed",
  "skill_id": "s14-operation-diagnosis",
  "run_id": "20260610120000",
  "hotel_id": "puyue",
  "hotel_name": "贵阳璞悦·奢电竞酒店",
  "platform": "fliggy",
  "channel_source": "飞猪",
  "channel_mode": "single",
  "period_start": "2026-06-01",
  "period_end": "2026-06-10",
  "raw_score": 72,
  "final_score": 68,
  "risk_level": "medium",
  "field_completeness": 0.85,
  "module_scores": [],
  "caps": [],
  "missing_fields": [],
  "formula_source": "runtime/calculator.py",
  "data_source": "hotel_pricing_tables",
  "execution_steps": [
    {"step": "S01_VALIDATE_INPUT", "status": "ok", "detail": "..."},
    {"step": "S02_FETCH_SOURCE", "status": "ok", "detail": "..."},
    {"step": "S03_NORMALIZE_FIELDS", "status": "ok", "detail": "..."},
    {"step": "S04_CALCULATE_MODULES", "status": "ok", "detail": "..."},
    {"step": "S05_APPLY_CAP_RULES", "status": "ok", "detail": "..."},
    {"step": "S06_RENDER_REPORT", "status": "ok", "detail": "..."},
    {"step": "S07_VALIDATE_OUTPUT", "status": "ok", "detail": "..."}
  ],
  "calculated_fields": ["hotel_id", "platform", "data_date", "time_grain", "revpar", "adr", "occupancy"],
  "mapped_fields": [
    {"field": "occupancy", "role": "formula", "source": "database/excel", "formula_module": "M01"}
  ],
  "field_contract_file": "references/excel_field_mapping.xlsx",
  "field_mapping_source": "config/excel_field_mapping.yaml",
  "feishu_message": "【S14 酒店 OTA 诊断报告已生成】\\n...",
  "approval_required": true,
  "dry_run": true,
  "report_file_path": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports/ota_diagnosis_report_demo.html",
  "report_url": "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html"
}
```

## HTML 报告

报告文件名固定：

```text
ota_diagnosis_report_demo.html
```

报告样式来自：

```text
templates/ota_diagnosis_report_demo.template.html
```

每次执行都会覆盖输出目录里的旧报告，避免飞书返回旧内容。

## 飞书接入边界

触发词不写在飞书入口代码里，统一写在：

```text
config/triggers.yaml
```

飞书入口或 OpenClaw Agent 读取 `config/triggers.yaml` 后判断是否调用 S14。

### 飞书输出格式：必须固定

S14 飞书输出格式**必须固定**，由 `runtime/reply_formatter.py` 单一来源生成。任何 Agent、Bot、模板都不能自行拼接飞书文本。

唯一允许的飞书输出链路（缺一不可）：

```text
1. Agent / 大模型只输出 JSON 对象
   ↓
2. Python 端用 json.loads(agent_output) 解析
   ↓
3. 解析成功 → runtime/reply_formatter.py::format_agent_json_output()
              → runtime/reply_formatter.py::format_feishu_message(data)
              → 得到下面【飞书固定模板】文本
   ↓
4. Python 把固定模板文本 send_text(open_id, reply)
   ↓
5. 解析失败 / 缺字段 → 返回"诊断结果格式异常，请重新生成。"
```

**禁止行为**（写死，违反任意一条即视为破坏 S14）：

- ❌ 禁止 Agent 直接生成自然语言、Markdown、表格、emoji 列表、模块清单发到飞书。
- ❌ 禁止 Bot/入口服务自行拼接"飞猪诊断：xx/100"开头、模块列表、得分表格、风险描述等业务内容。
- ❌ 禁止把 Agent 原文（如 deepseek 输出的 "飞猪诊断：68/100 中风险 | 仅上架 1 房型..."）作为飞书消息发送。
- ❌ 禁止在 Feishu Bot 代码里再写一份 `format_feishu_message`、再写一份风险文案、再写一份模块表。
- ❌ 禁止 Bot 修改综合得分、风险等级、报告链接、字段缺口，只允许原样转发 Python 拼好的文本。

飞书入口或 OpenClaw Agent 调用的**唯一正确示例**：

```python
from runtime.feishu_adapter import build_feishu_reply_from_agent_output, build_feishu_reply
from runtime import S14OperationDiagnosis

# 方式 A：Agent 先输出 JSON，再交给 Python 固定排版
agent_output = call_s14_agent(inputs)  # 必须是 JSON 字符串
reply = build_feishu_reply_from_agent_output(agent_output)
send_text(open_id, reply)

# 方式 B：直接走 S14 Skill，让 Python 一次性产出 feishu_message
result = S14OperationDiagnosis(config).execute(inputs)
reply = build_feishu_reply(result)  # 内部直接用 result["feishu_message"]
send_text(open_id, reply)
```

**禁止示例**（以下写法一律不允许）：

```python
# ❌ 禁止：自己拼飞书文本
reply = f"飞猪诊断：{score}/100 {risk} | {problems}"
send_text(open_id, reply)

# ❌ 禁止：把 Agent 原文直接发出去
reply = call_agent_text(inputs)  # 可能是 Markdown、表格、emoji
send_text(open_id, reply)
```

### 飞书固定模板（不可改）

`runtime/reply_formatter.py::format_feishu_message` 生成的文本必须严格符合下面模板，**一个字符都不能变**：

```text
【S14 酒店 OTA 诊断报告已生成】

酒店：{hotel_name}
周期：{period_start} 至 {period_end}
综合得分：{final_score:.0f} / 100
风险等级：{risk_text}

报告链接：
{report_url}

说明：当前为 S14 测试机器人返回结果，不影响正式酒店 OTA Agent。
```

字段来源约束：

- `hotel_name`：来自 S14 诊断结果，不允许 Bot 自行改名。
- `period_start` / `period_end`：必须是 `YYYY-MM-DD`，来自 S14 入参。
- `final_score`：必须是 0-100 的整数，由 S14 计算，Bot 不得改写。
- `risk_text`：必须是 `高风险` / `中风险` / `低风险` 之一，由 `risk_label(score)` 计算。
- `report_url`：必须是 S14 返回的报告链接，Bot 不得改写、缩短、附加参数。

### Agent JSON 契约（不可改）

Agent 输出 JSON 时，必须遵守：

- 必须是合法 JSON 对象（`json.loads` 能解析）。
- 不得输出 Markdown、代码块、解释文字、自然语言总结、emoji 列表。
- 最少包含 5 个字段：`hotel_name`、`period_start`、`period_end`、`final_score`、`report_url`。
- 缺字段或解析失败时，Python 端必须返回 `诊断结果格式异常，请重新生成。`，**不允许 Bot 自行补字段、猜分数、改风险等级**。

飞书回复不得展示：

- MySQL DSN
- 原始订单明细
- 角色表
- API 密钥
- 完整 runtime JSON
- 源码和服务器内部路径
- Agent 自行拼接的"模块清单 / emoji 列表 / 自由文本"

## 测试

本地/服务器冒烟测试：

```bash
python3 -B tests/smoke_test.py
```

测试会创建临时 SQLite 数据库，模拟 `hotel_pricing` 业务表样例数据，调用 Skill，验证 8 个模块分和 HTML 报告。
