# OpenClaw 项目适配说明

## 1. 目标

本工程包不仅提供 17 个 `SKILL.md`，还把整个 OpenClaw workspace 适配成“酒店 OTA AI 数字员工总控 Agent”。

适配方式是不改 OpenClaw 源码，而是通过：

- 根目录 bootstrap 文件：`AGENTS.md`、`TOOLS.md`、`BOOTSTRAP.md`
- Agent 配置样例：`config/openclaw.example.json`
- 总控提示词：`requirements/OpenClaw总控Agent提示词.md`
- Skill 调度规则和 runtime 工具策略

让 OpenClaw 在进入项目后自动按酒店 OTA 项目上下文工作。

## 2. 三个根目录文件

`AGENTS.md`：

- 定义总控 Agent 身份。
- 固化 P0/P1 优先级。
- 固化 skill 调度规则。
- 固化安全审批底线和 API fallback。

`TOOLS.md`：

- 定义 runtime 调用规则。
- 说明稳定输入输出优先走 `runtime/hotel_ota_runtime.py`。
- 说明 Windows/PowerShell 使用 `--biz-content-b64`。

`BOOTSTRAP.md`：

- 定义每次进入 workspace 的读取顺序。
- 定义多 skill 串联主线。
- 定义 API 未确定和审批执行链路。

## 3. Agent 配置

`config/openclaw.example.json` 保留 `agents.defaults.skills`，同时新增命名 agent：

```json
{
  "id": "hotel-ota-chief",
  "workspace": "/opt/openclaw/workspaces/hotel-ota-ai",
  "repoRoot": "/opt/openclaw/workspaces/hotel-ota-ai",
  "contextInjection": "always",
  "skills": ["s01-control-config", "s02-operating-snapshot"]
}
```

实际配置中包含 17 个 skill。这样旧部署使用默认 agent 时不丢 skill，新部署可以明确使用 `hotel-ota-chief`。

## 4. 推荐启动顺序

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
openclaw skills list --agent hotel-ota-chief
openclaw skills check --agent hotel-ota-chief
openclaw skills info s05-revenue-decision --agent hotel-ota-chief
```

如果当前 OpenClaw CLI 版本不支持 `--agent` 参数，使用默认命令：

```bash
openclaw skills list
openclaw skills check
openclaw skills info s05-revenue-decision
```

并确认默认 agent 已读取 `agents.defaults.skills`。

## 5. 总控调度验收

飞书或 agent 对话中测试：

```text
@机器人 API 还没确定怎么跑？
@机器人 今天璞悦经营情况怎么样？
@机器人 做一次璞悦 OTA 运营诊断。
@机器人 给璞悦生成今日销售基准线。
@机器人 现在进度是否落后？原因是什么？
@机器人 今天璞悦需要调价吗？只给 dry-run 建议。
@机器人 确认执行前先预览 KING 房型 Mtop 今天平日价159、周末价189，不要真实执行。
```

预期：

- API 未确定问题优先引用统一数据契约、渠道 API 策略和脚本固化边界。
- 经营情况触发 S2。
- 运营诊断触发 S14。
- 销售目标触发 S15。
- 进度偏差触发 S16。
- 调价建议触发 S5。
- 执行预览触发 S6，且只做 dry-run。

## 6. 不做的事

- 不修改 OpenClaw 源码。
- 不使用 `systemPromptOverride` 覆盖 OpenClaw 原生系统提示。
- 不把任一 API 作为 P0/P1 硬依赖。
- 不开启无审批真实写接口。
