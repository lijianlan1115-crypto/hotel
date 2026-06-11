# Hotel OTA AI Memory

## 项目长期规则

- 本项目是 OpenClaw 酒店 OTA 数字员工 workspace。
- 权限只认 `/etc/hotel-ota-ai/feishu-role-map.json` 和 runtime 返回的 `auth_context`。
- memory/embedding 只用于上下文召回，不能用于授权、审批、角色识别、live 执行或业务事实判断。
- S2/S5/S15/S16 必须先检查 `freshness_status`。
- `captured_at` 是查询时间，不代表业务数据日期。
- 旧数据只能用于历史/演示分析，不得生成今日快报或真实调价审批。
- 真实调价、房量、推广、评论发布必须经过 dry-run、admin/owner 审批和 live 开关。
- 当前 MySQL 报表库可能是历史导入库，不一定有今日实时数据。
- Gateway 推荐采用 system service：`openclaw-gateway.service`。当前服务器不要再使用 `systemctl --user` 或 `openclaw gateway restart` 重启 Gateway。

## 跨会话记忆规则

- 目标是沉淀酒店运营经验，不保存全量飞书聊天。
- 短期会话记忆只用于当前会话连续性。
- 长期规则记忆用于召回安全底线、业务口径、字段规则、输出规范和杨总确认结论。
- 运营案例记忆用于召回脱敏测试结果、诊断复盘、调价 dry-run 复核和问题关闭记录。
- 如果用户问“上次怎么说的/之前测过什么/杨总确认过什么”，先检索长期记忆；没有归档时必须说明没有可检索归档，不得编造。
- 记忆里的历史经验不能当成当前经营事实；当前经营事实必须重新读取 runtime、数据库、API、manual upload 或 RPA。
- 审批、权限、角色识别、live 执行和数据新鲜度不能依赖记忆。

## 运营案例归档格式

```text
日期：
场景：
触发问题：
适用 skill：
机器人表现：
人工判断：
正确结论：
数据来源：
数据日期/新鲜度：
不适用范围：
安全注意：
是否已沉淀到工程规则：
关联问题编号：
```

服务器私有归档目录建议：

```text
/var/lib/hotel-ota-ai/memory/cases/
/var/lib/hotel-ota-ai/memory/daily-summary/
```

## 协作约束

- 不记录 API key、数据库 DSN、密码、token、真实飞书 ID、审批凭证、客户姓名、房号、订单号。
- 不记录订单行级明细、数据库原始表、CSV/XLSX/JSON 原始数据、完整 runtime JSON。
- 新成员先读 `README.md`、`AGENTS.md`、`TOOLS.md`、`BOOTSTRAP.md` 和 `requirements/OpenClaw实施教程.md`。
- 长期记忆和归档规范见 `requirements/数字员工长期记忆与归档规范.md`。
- 服务器代码以 GitHub `origin/main` 为准；服务器私有配置只放 `/etc/hotel-ota-ai/`。
