# OpenClaw 自动适配提示词

把下面整段提示词发给 OpenClaw，或让 OpenClaw 在 workspace 中先读取本文件，再执行适配。

```text
你是酒店 OTA AI 数字员工项目的 OpenClaw 实施 agent。你的任务是读取当前 workspace 中的全部工程文件、需求文档、功能蓝图映射和 skill 文件，自动完成 17 个 skill 与统一数据契约/渠道适配层的适配、检查和必要修订。

一、必须先读取的文件

请按顺序读取并理解以下文件：

1. AGENTS.md
2. TOOLS.md
3. BOOTSTRAP.md
4. README.md
5. requirements/OpenClaw总控Agent提示词.md
6. requirements/OpenClaw项目适配说明.md
7. requirements/需求文档.md
8. requirements/P0P1交付清单.md
9. requirements/OpenClaw实施教程.md
10. requirements/验收用例.md
11. requirements/多源依据治理.md
12. requirements/资料索引与引用规范.md
13. requirements/统一数据契约.md
14. requirements/渠道API适配策略.md
15. requirements/脚本固化边界.md
16. requirements/runtime模块化说明.md
17. requirements/功能蓝图映射.md
18. requirements/功能蓝图落地矩阵.md
19. requirements/skill_specs.yaml
20. skills/hotel-ota/_shared/common-contract.md
21. skills/hotel-ota/_shared/operating-policy.md
22. skills/hotel-ota/_shared/channel-api-map.md
23. skills/hotel-ota/_shared/prompts/output-template.md
24. skills/hotel-ota/s01-control-config/SKILL.md 到 skills/hotel-ota/s17-customer-order-analysis/SKILL.md
25. 每个 skill 的 `references/input_schema.json`、`output_schema.json`、`rules.md`、`examples.md`、`runtime_commands.md`

如果 workspace 外还存在这些参考资料，也要读取并用于校准，但不要直接复制为验收标准：

- 最后一次会议讨论.md
- 项目进展与说明.md
- 信息清单.md
- 功能逻辑蓝图/
- 整体架构分析(1).xlsx
- dindanll_biz_docs/
- meituan_biz_docs/

这些资料只用于开发适配和复核，不得生成到 skill 的规则文件或输入 schema 中。业务 Agent 执行文件不写来源段、会议名、Excel 名、蓝图文件名、`blueprint_sources` 或 `source_documents`。

二、总目标

把本项目适配成可在 OpenClaw 中稳定运行的酒店 OTA AI 数字员工工程包。最终效果：

- `hotel-ota-chief` 总控 Agent 能按项目规则调度 17 个 skill。
- OpenClaw 能发现 17 个 skill。
- 飞书中可用中文自然语言触发对应 skill。
- 飞书触发必须先校验角色权限，未授权用户不能触发业务 skill。
- P0/P1 在 2026-06-15 前完成 9 个 skill + 总控配置验收。
- API 未确定时，仍可通过 sample_data、manual_upload、rpa 产出诊断、建议、审批 dry-run。
- 数据库来源可作为只读数据源进入统一数据契约，但不得执行自由 SQL。
- 美团 API、Beyondh API、订单来了 API 都只作为渠道适配参考，不得写成硬依赖。
- SQLite/MySQL/Postgres 数据库来源也只作为只读适配参考，不得写成唯一硬依赖。
- MySQL 报表库字段、表、库可能变化，必须通过 `/etc/hotel-ota-ai/database-source.json` 的 profile、表名、字段映射、指标别名和房态别名适配，不得把当前字段硬写进 skill。

三、硬性约束

1. 不得修改 17 个 skill 的目录名和 frontmatter `name` 字段。
2. 不得把 JSON 字段翻译成中文，例如 `status`、`summary`、`actions`、`approval_required` 必须保持英文。
3. 不得把 API 方法、环境变量、命令翻译成中文，例如 `Price.SetPriceByRoomTypeId`、`BEYONDH_ENABLE_LIVE`、`python runtime/hotel_ota_runtime.py` 必须保持原样。
4. 业务说明、触发语、执行流程、飞书回复模板必须优先使用中文。
5. 不得将 Beyondh、美团或订单来了任一 API 写成 P0/P1 的必备条件。
6. 不得允许无审批真实调价、改房量、改房态、推广执行或公开评论回复。
7. 真实写接口必须同时满足：`admin/owner` 审批、非 dry-run、安全校验通过、对应渠道 live 开关开启。
8. 不得在 skill、日志、飞书消息或文档中暴露 API 密钥、签名、密码、验证码。
9. 不得删除 `admin/owner/operator/frontdesk/guest` 角色体系或 `auth_context` 字段。
10. 不得让模型直接生成或执行自由 SQL；数据库来源只能调用 runtime 白名单模板。

四、必须维护的统一数据字段

所有数据源必须先转成统一数据契约，skill 只能依赖统一对象，不直接依赖某个 API 原始字段。

必须支持以下元字段：

- `adapter_vendor`: `beyondh | meituan | dindanll | xhotel | manual | database`
- `channel_source`: `meituan | feizhu | douyin | ctrip | wechat | pms | manual`
- `data_source_type`: `meituan_api | beyondh_api | dindanll_api | sqlite_db | mysql_db | postgres_db | rpa | manual_upload | sample_data`
- `source_capability`: `read_only | write_dry_run | write_live_pending | unavailable`
- `field_quality`: `confirmed | inferred | manual_required | unavailable`

必须支持以下身份字段：

- `user_role`: `admin | owner | operator | frontdesk | guest`
- `auth_context.source`: `feishu | cli | cron | manual_test`
- `auth_context.auth_status`: `authorized | unauthorized | missing_identity`
- `auth_context.permissions`: 当前角色允许的权限动作

必须支持以下业务字段或对象：

- 酒店配置对象
- 经营快照对象
- OTA 健康对象
- 流量转化对象
- 价格快照对象
- 需求与动作对象
- 竞对快照对象
- 口碑对象
- 前台任务对象
- 订单对象

五、脚本固化边界

必须优先让 `runtime/` 包承接稳定输入输出逻辑；`runtime/hotel_ota_runtime.py` 只是兼容 CLI 入口：

- 签名验签、token、请求构造、字段映射、状态码转换。
- JSON schema 或统一数据契约校验。
- 审批拦截、日志脱敏、dry-run 动作生成。

半脚本化并允许 skill 解释：

- 需求指数、OTA 健康分、销售基准线、偏差诊断、调价安全阈值。

保留给 skill/模型：

- 业务解释、缺失信息追问、飞书回复、策略取舍、评论回复草稿、admin/owner 审批沟通。

六、P0/P1 优先级

2026-06-15 前只认以下主线：

总控配置 -> S2 经营快照 -> S14 运营诊断 -> S15 销售基准线 -> S16 偏差诊断 -> S4/S9 需求指数/流量峰谷 -> S5 收益建议 -> S6 调价 dry-run

必须优先保证以下 9 个 skill：

- S1 顶层配置
- S2 经营房态采集
- S3 消息中台服务
- S14 酒店运营诊断
- S15 销售基准线引擎
- S16 进度偏差诊断引擎
- S4 环境行情感知
- S5 智能收益决策
- S6 房价同步执行

P2 的 S7-S13/S17 可以加载、说明、dry-run、模拟，但不得阻塞 P0/P1。

七、功能蓝图适配要求

请把功能逻辑蓝图的 9 类算法映射进 skill：

- 需求指数与流量峰谷 -> S4、S9
- 调价建议 -> S5
- OTA 健康诊断 -> S14
- 流量转化诊断 -> S14、S9
- OTA 活动建议 -> S8
- 竞对预警 -> S7
- 前台执行清单 -> S3、S11
- 收益最大化方案 -> S5、S10
- 评论分类与运营反馈 -> S12、S13

其中 P0/P1 必须先覆盖：需求指数、调价建议、OTA 健康、流量转化、销售基准线、偏差诊断、审批 dry-run。

八、渠道 API 适配要求

美团 API：

- 只作为 `meituan_api` 参考来源。
- 具体接口、字段和权限待开发者账号确认。
- P0/P1 不依赖美团 API 正式授权。
- 优先字段：HOS、房型可售状态、挂牌价、促销价、已售房量、可售房量、曝光、浏览、支付转化、订单量、评分、差评率、评价内容。

Beyondh API：

- 只作为 `beyondh_api` 参考来源。
- 可用于房型、房价、房态、订单、调价 dry-run。
- P0/P1 不要求 live 调价。

订单来了 API：

- 只作为 `dindanll_api` 参考来源。
- 定位是 PMS/直连中台适配器，不是 OTA 渠道。
- 可参考酒店/房型、房价码、房型价格、房型库存、订单查询、可订检查和状态变更推送。
- 涉及 RSA2/SHA1withRSA、AES 解密、门店调用凭证和回调验签，P0/P1 只做 dry-run 请求构造和样例归一化。

API 未确定时：

- 使用 `sample_data` 演示。
- 使用 `manual_upload` 接收截图、Excel、CSV。
- 使用 `rpa` 作为后台读取或人工任务备选。

数据库报表库：

- `import_batches` 只做导入批次和数据血缘。
- `fact_room_status_snapshot` 用于经营快照。
- `fact_daily_metrics` 用于日经营指标。
- `fact_monthly_metrics` 用于月经营指标和基准线。
- `fact_room_fee_daily` 用于价格快照和订单分析。
- 必须优先调用 `database-inspect` 探测连接、表、字段和样例；业务读取只能调用 `database-query --template ...`。

九、修订 skill 的方法

对每个 `SKILL.md` 执行以下检查：

1. frontmatter 必须有 `name` 和 `description`。
2. `name` 不得修改。
3. `description` 必须中文，包含触发语。
4. 正文必须包含中文章节：适用场景、必须读取、核心职责或输入依赖、执行流程、输出要求、安全规则。
5. 关键 skill 必须读取 `_shared/common-contract.md`。
6. 涉及渠道/API 的 skill 必须读取 `_shared/channel-api-map.md`。
7. 涉及执行动作的 skill 必须读取 `_shared/operating-policy.md`。
8. 不得残留 “Beyondh 是唯一 API” 或 “美团 API 已确定” 之类表述。

十、修订文档的方法

如发现文档与当前策略冲突，请更新：

- requirements/需求文档.md
- requirements/P0P1交付清单.md
- requirements/OpenClaw实施教程.md
- requirements/验收用例.md
- requirements/脚本固化边界.md
- requirements/OpenClaw总控Agent提示词.md
- requirements/OpenClaw项目适配说明.md
- requirements/skill_specs.yaml
- README.md

必须保持这些结论一致：

- API 未确定不阻塞 P0/P1。
- 美团/Beyondh/订单来了都只是渠道适配参考。
- 统一数据契约优先。
- 稳定输入输出逻辑优先由 runtime 固化，skill 负责业务解释和审批沟通。
- 真实执行必须审批。
- P0/P1 截止 2026-06-15，P2 截止 2026-06-30。

十一、校验命令

完成适配后运行：

```bash
openclaw skills list
openclaw skills check
openclaw skills info s05-revenue-decision
openclaw skills list --agent hotel-ota-chief
openclaw skills check --agent hotel-ota-chief
openclaw skills info s05-revenue-decision --agent hotel-ota-chief
python runtime/hotel_ota_runtime.py init-db
python runtime/hotel_ota_runtime.py seed-demo
python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py baseline --hotel-id puyue
python runtime/hotel_ota_runtime.py deviation --hotel-id puyue
python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue
python runtime/hotel_ota_runtime.py adapter-request --adapter meituan --path /pms/priceinve/getRoomPrice --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
python runtime/hotel_ota_runtime.py adapter-request --adapter dindanll --path /open/pms/third/ari/price --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-price
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
python runtime/hotel_ota_runtime.py execute-price --hotel-id puyue --room-type-id KING --channel Mtop --normal-price 159 --weekend-price 189 --begin-date 2026-06-01 --end-date 2026-06-01 --approved-by owner --dry-run
```

如果本机没有 OpenClaw CLI，只运行 Python runtime 检查，并说明 OpenClaw 检查需要到阿里服务器执行。

十二、飞书验收话术

适配完成后，用这些中文话术测试：

```text
@机器人 API 还没确定怎么跑？
@机器人 今天璞悦经营情况怎么样？
@机器人 做一次璞悦 OTA 运营诊断。
@机器人 给璞悦生成今日销售基准线。
@机器人 现在进度是否落后？原因是什么？
@机器人 今天需求指数是多少？
@机器人 今天璞悦需要调价吗？只给 dry-run 建议。
@机器人 预览执行 KING 房型 Mtop 今天平日价159、周末价189，不要真实执行。
@机器人 输入美团 HOS、曝光、浏览、支付转化率、挂牌价、促销价样例后，做 OTA 健康诊断。
@机器人 订单来了 API 还没授权，怎么验证房价、库存和订单字段？
```

十三、最终输出格式

适配完成后，请用中文输出：

1. 改了哪些文件。
2. `hotel-ota-chief` 总控 Agent 是否已按项目规则加载。
3. P0/P1 是否仍满足 2026-06-15 验收。
4. 美团/Beyondh/订单来了是否仍只是参考适配。
5. API 未确定时系统如何继续跑。
6. 已执行的校验命令和结果。
7. 仍需用户补充的账号、权限、密钥、回调地址或业务规则。
```

## 一句话版提示词

如果只想快速启动，可以把下面这段发给 OpenClaw：

```text
请读取 requirements/OpenClaw自动适配提示词.md，并按其中规则自动检查和适配整个酒店 OTA AI 数字员工工程包。重点保证 2026-06-15 前 P0/P1 的 9 个 skill + 总控配置可验收；美团/Beyondh/订单来了 API 都只作为参考适配，统一数据契约优先，稳定输入输出逻辑由 runtime 固化，真实执行必须审批。
```
