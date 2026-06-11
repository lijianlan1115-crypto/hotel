# 酒店 OTA AI 数字员工 OpenClaw 工程包

这是可同步到阿里服务器 OpenClaw workspace 的酒店 OTA 数字员工工程包。

## 6 月 15 日优先目标

2026-06-15 前必须完成并验收：

- P0+P1 共 9 个 skill：`S1/S2/S3/S14/S15/S16/S4/S5/S6`
- OpenClaw 总控配置：`hotel-ota-chief` agent、workspace、飞书入口、skill allowlist、cron、审批安全、共享运行时、渠道 dry-run
- 飞书权限：角色表区分 `admin/owner/operator/frontdesk/guest`，未授权用户默认阻断
- 项目记忆：`MEMORY.md` 只保存长期规则和协作上下文；不得用于授权、审批或业务事实判断
- 可演示闭环：经营快照 -> 运营诊断 -> 销售基准线 -> 偏差诊断 -> 收益建议 -> 审批后调价 dry-run
- API 未确定也可演示：使用统一数据契约接收 `meituan_api`、`beyondh_api`、`dindanll_api`、`sqlite_db`、`mysql_db`、`postgres_db`、`rpa`、`manual_upload`、`sample_data`。

P2 的 `S7-S13/S17` 仍在工程包内，可加载、可触发、可演示说明，但不阻塞 6 月 15 日交付。

## 包含内容

- `AGENTS.md`：OpenClaw 酒店 OTA 总控 Agent 规则。
- `TOOLS.md`：runtime 工具调用规则。
- `BOOTSTRAP.md`：workspace 启动读取顺序和调度主线。
- `skills/hotel-ota/`：17 个 OpenClaw skill。
- `skills/hotel-ota/_shared/`：中文共享契约、安全策略、渠道 API 映射、飞书输出模板。
- `requirements/渠道API适配策略.md`：美团、Beyondh、订单来了、RPA、人工上传的统一适配规则。
- `requirements/统一数据契约.md`：skill 统一读取的数据对象和字段质量等级。
- `requirements/脚本固化边界.md`：说明哪些输入输出逻辑必须由 runtime 固化，哪些交给 skill/模型。
- `requirements/功能蓝图映射.md`：把新增功能逻辑蓝图和 Excel 五层架构映射到 17 个 skill。
- `requirements/OpenClaw自动适配提示词.md`：给 OpenClaw/agent 读取后自动适配工程包的完整提示词。
- `requirements/OpenClaw总控Agent提示词.md`：可直接配置给 `hotel-ota-chief` 的总控 prompt。
- `requirements/OpenClaw项目适配说明.md`：说明如何将 OpenClaw workspace 适配成本项目总控 Agent。
- `requirements/协作开发与测试入门教程.md`：给新协作者快速理解文件、修改 skill、测试 runtime 和更新服务器的入口教程。
- `requirements/Skill测试协作手册.md`：定义团队只测试、张宇翔统一修改的协作规则。
- `requirements/P0P1技能测试矩阵.md`：按 A/B/C/D 分组列出 P0/P1 skill 测试话术、命令和通过标准。
- `requirements/Skill问题记录模板.md`：统一记录 bug、期望输出、严重程度、证据和关闭标准。
- `runtime/hotel_ota_runtime.py`：dry-run、Beyondh/美团/订单来了请求构造、样例归一化、SQLite 缓存、审批、日志工具。
- `requirements/`：需求文档、实施教程、P0/P1 交付清单、验收用例、机器可读 skill spec。
- `config/`：OpenClaw 配置样例、飞书角色表样例和环境变量样例。
- `cron/`：OpenClaw 定时任务脚本。
- `examples/`：飞书测试话术。

## 服务器部署位置

复制本目录内容到：

```bash
/opt/openclaw/workspaces/hotel-ota-ai
```

然后按教程执行：

```bash
requirements/OpenClaw实施教程.md
```

## 安全默认值

调价、房量、房态、推广、公开评论回复默认都是 dry-run。美团、Beyondh、订单来了 API 和数据库来源都只是参考适配；数据库来源 V1 只读，禁止自由 SQL。真实写接口必须同时满足对应渠道 live 开关，例如：

```bash
BEYONDH_ENABLE_LIVE=1
MEITUAN_ENABLE_LIVE=1
DINDANLL_ENABLE_LIVE=1
```

MySQL 报表库通过 `/etc/hotel-ota-ai/database-source.json` 配置化接入，支持 `import_batches`、`fact_room_fee_daily`、`fact_room_status_snapshot`、`fact_daily_metrics`、`fact_monthly_metrics` 这类报表表结构。字段、表或库变化时优先修改私有 mapping profile，不修改 17 个 skill；`guest_name`、`room_no`、`order_no`、`operator_name` 默认脱敏。

并且有 `admin/owner` 审批。飞书未授权用户按 `guest` 阻断；密钥和真实角色表只能放在服务器私有配置或环境变量中，不写入 skill、文档、日志或飞书消息。
