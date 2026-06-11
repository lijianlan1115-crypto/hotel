# S14 酒店运营诊断 规则

## 来源依据
- 用户最新指令和安全底线优先。
- **S14 独立运行优先**：OpenClaw 只能传控制字段；S14 不接收任何其他 Skill 输出作为输入。
- **受控数据源唯一事实来源**：正式运行时，经营、OTA、推广、口碑、人工表单镜像等事实数据必须由 `runtime/data_fetcher.py` 从数据库或上传 Excel 读取并映射。
- **数据库实时数据**：`operating_snapshot`、`price_snapshot`、`order_snapshot`、`daily_metrics`、`monthly_metrics`
- **本地 SQLite 数据库**：`HOTEL_OTA_DB` 环境变量指定路径（默认 `./data/hotel_ota.sqlite`）
- **MySQL 数据库**：通过 `HOTEL_OTA_DB_DSN` 配置连接，支持 `metric_aliases` 归一化
- API 文档只进入字段适配，不直接决定业务策略。

## 输入字段
- OpenClaw 输入只允许 `references/input_schema.json` 中定义的控制字段。
- 禁止输入 `metrics`、`business_fields`、`json_payload`、`manual_diagnosis_input`、`upstream_skill_output`。
- 下列诊断事实字段必须从数据库或上传 Excel 映射得到，不得由上游 Skill 作为输入传入：
  - `revpar`
  - `adr`
  - `occupancy`
  - `available_room_nights`
  - `exposure`
  - `views`
  - `payment_conversion_rate`
  - `promo_cost`
  - `rating_total`

## 判断逻辑
1. 平台官方评分优先，自建漏斗评分辅助
2. 先修转化再做流量或降价
3. 输出 A/B 任务和责任人

## 数据库来源
- S14 正式运行缺少 `db_kind` 或 `db_dsn` 时必须失败，不允许降级为上游 Skill 输出。
- 可读取 `database-query --template operating_snapshot`、`price_snapshot`、`order_snapshot`、`daily_metrics` 作为诊断证据。
- 数据库证据必须标注 `data_source_type=sqlite_db/mysql_db/postgres_db` 和字段质量。
- MySQL 日经营指标通过 `metric_aliases` 归一化，不直接解释 `metric_name` 原始文本。
- 数据库字段缺失时继续使用 API/RPA/manual/sample 兜底。
- sample/demo OTA 字段必须显式标记 `demo_data`，不得包装成正式数据库诊断。
- `conversion-diagnosis` 生产默认短摘要；完整 evidence 仅在 CLI `--debug` 或 `HOTEL_OTA_FEISHU_DEBUG=1` 时显示。
- 当 RevPAR 为 0 但 ADR 和出租率存在时，优先提示字段映射/导入风险，不直接判定经营异常。

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。
- 输出必须包含或引用 `data_business_date`、`data_snapshot_time`、`freshness_status`。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。
