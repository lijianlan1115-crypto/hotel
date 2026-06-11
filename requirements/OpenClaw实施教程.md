# OpenClaw 实施教程

本教程按 2026-06-15 的 P0/P1 交付优先级编排：先让 9 个核心 skill 和总控配置跑通，再启用 P2 扩展能力。

## 0.0 当前重点坑位

- 飞书身份：`ou_...` 默认是 Open ID，角色表和测试命令优先使用 `open_id` / `--open-id`。如果误用 `--user-id ou_...`，runtime 会兼容匹配但输出 `identity_warning`，应尽快改回 `--open-id`。
- 权限边界：权限只认 `/etc/hotel-ota-ai/feishu-role-map.json` 和 runtime 的 `auth_context`；用户自称、历史对话、全局记忆、`USER.md` 都不能授权。
- 记忆边界：embedding/memory 只做上下文召回，不能保存密钥、DSN、真实飞书 ID、审批凭证、客户隐私，也不能参与审批或 live 执行。
- 数据新鲜度：`captured_at` 是查询时间，不是业务数据日期。S2/S5/S15/S16 必须检查 `freshness_status`，旧数据只能按历史/演示口径输出。
- Cron 失败：`Request was aborted` 只代表 cron isolated session、模型调用或工具执行被中断；不能因此补造经营结论，必须先看 runtime 输出和数据新鲜度。

## 0. 两种实施路径

本教程分两种场景：

- 新服务器全量部署：服务器还没有 `/opt/openclaw/workspaces/hotel-ota-ai`，按第 1-11 节执行。
- 旧服务器更新：服务器已经部署过本项目，只需要把本地新版本覆盖到现有 OpenClaw workspace，按第 12 节执行。

当前阿里云服务器的实测基线：

- 系统：Alibaba Cloud Linux 3.2104 U12.3。
- 用户：`root`。
- OpenClaw：2026.5.28。
- Python：系统 `python3` 可能是 3.6.8，项目运行应使用 `.venv` 内的 Python 3.11.13。
- OpenClaw agent：当前可先使用默认 `main`，并让 `main` 指向 `/opt/openclaw/workspaces/hotel-ota-ai`。
- 已验证：runtime、17 个 skill、`openclaw skills check` 已能跑通。
- 当前已知阻塞：OpenClaw cron 可能被 Gateway device scope/pairing 卡住，短期可用 Linux `crontab` 兜底。

旧服务器更新不需要重装 OpenClaw，也不需要重新处理飞书、模型和 cron。更新重点是：

- 备份现有 workspace。
- 覆盖工程文件。
- 保留 `.env`、`.venv`、`data/`、`logs/` 等服务器运行状态。
- 验证 runtime 新命令和 17 个 skill references。

## 1. 服务器准备

目标目录：

```bash
sudo mkdir -p /opt/openclaw/workspaces/hotel-ota-ai
sudo mkdir -p /var/lib/hotel-ota-ai
sudo mkdir -p /var/log/hotel-ota-ai
```

把本工程包内容复制到：

```bash
/opt/openclaw/workspaces/hotel-ota-ai
```

推荐权限：

如果 OpenClaw 以 `root` 运行，按当前阿里云实测方式处理：

```bash
chown -R root:root /opt/openclaw/workspaces/hotel-ota-ai /var/lib/hotel-ota-ai /var/log/hotel-ota-ai
chmod -R 755 /opt/openclaw/workspaces/hotel-ota-ai
chmod 700 /var/lib/hotel-ota-ai
chmod 755 /var/log/hotel-ota-ai
```

如果 OpenClaw 以普通用户运行：

```bash
sudo chown -R "$USER":"$USER" /opt/openclaw/workspaces/hotel-ota-ai /var/lib/hotel-ota-ai /var/log/hotel-ota-ai
```

工程包放好后，正确结构应该是：

```text
/opt/openclaw/workspaces/hotel-ota-ai/AGENTS.md
/opt/openclaw/workspaces/hotel-ota-ai/BOOTSTRAP.md
/opt/openclaw/workspaces/hotel-ota-ai/TOOLS.md
/opt/openclaw/workspaces/hotel-ota-ai/runtime
/opt/openclaw/workspaces/hotel-ota-ai/skills
/opt/openclaw/workspaces/hotel-ota-ai/requirements
```

错误结构是多套一层：

```text
/opt/openclaw/workspaces/hotel-ota-ai/openclaw-hotel-ota-ai/AGENTS.md
```

如果上传后多了一层目录，可以这样整理：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
find openclaw-hotel-ota-ai -mindepth 1 -maxdepth 1 -exec mv -t . {} +
rmdir openclaw-hotel-ota-ai
```

不要执行：

```bash
mv openclaw-hotel-ota-ai/.* .
```

因为 `.*` 可能匹配特殊目录，容易导致异常或卡住。

## 2. 检查 OpenClaw

```bash
openclaw --version
openclaw update
openclaw doctor
openclaw status
```

飞书渠道需要 OpenClaw 2026.4.25 或更高版本。

## 2.1 配置 Python 3.11 虚拟环境

阿里云服务器实测系统 `python3` 可能是：

```text
Python 3.6.8
```

不要用这个版本创建项目虚拟环境。当前 runtime 建议使用 Python 3.11：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai

dnf install -y python3.11 python3.11-pip python3.11-devel
python3.11 --version

rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate

python --version
python -m pip install --upgrade pip setuptools wheel
```

后续服务器命令建议优先写成：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py --help
```

不要依赖裸 `python3`，因为它可能仍指向系统 3.6。

## 3. 配置环境变量

复制环境变量样例：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
cp -n config/env.example .env
chmod 600 .env
```

填写真实值。API 未确定时可以先留空，P0/P1 使用 `sample_data/manual_upload/rpa` 验收：

```bash
BEYONDH_BASE_URL=https://openapi.beyondh.com
BEYONDH_DOMAIN=客户 PMS domain
BEYONDH_CHANNEL_KEY=客户 ChannelKey
BEYONDH_APP_KEY=客户 AppKey
BEYONDH_ORG_ID=客户 OrgId
BEYONDH_ENABLE_LIVE=0
MEITUAN_BASE_URL=https://api-open-cater.meituan.com
MEITUAN_DEVELOPER_ID=
MEITUAN_SIGN_KEY=
MEITUAN_APP_AUTH_TOKEN=
MEITUAN_ENABLE_LIVE=0
DINDANLL_BASE_URL=https://open.dingdanll.com
DINDANLL_APP_CODE=
DINDANLL_AUTH_ACCESS_TOKEN=
DINDANLL_VERSION=3.0
DINDANLL_ENABLE_LIVE=0
```

先保持所有 `*_ENABLE_LIVE=0`。6 月 15 日前的验收重点是 dry-run、样例归一化和审批链路，不是无审批真实调价或真实 API 写入。

飞书角色权限配置指向服务器私有文件：

```bash
HOTEL_OTA_AUTH_CONFIG=/etc/hotel-ota-ai/feishu-role-map.json
HOTEL_OTA_DB_SOURCE_ENABLE=0
HOTEL_OTA_DB_KIND=sqlite
HOTEL_OTA_DB_PROFILE=report_mysql_prod
HOTEL_OTA_DB_DSN=
HOTEL_OTA_DB_READONLY=1
HOTEL_OTA_DB_MAPPING_CONFIG=/etc/hotel-ota-ai/database-source.json
```

真实角色表不要提交到工程包，不要写进 skill 或飞书消息。

数据库来源 V1 只读。真实 DSN、用户名、密码只放服务器 `.env` 或 SecretRefs，不写入文档、skill、日志或飞书消息。MySQL 报表库必须通过 `/etc/hotel-ota-ai/database-source.json` 配置 profile、表名、字段映射、指标别名和房态别名；以后字段、表或库变化时优先改该私有配置。

当 `HOTEL_OTA_DB_SOURCE_ENABLE=1` 时，P0/P1 主命令会数据库优先：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py baseline --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py deviation --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
```

注意：SSH 手动测试和 OpenClaw Gateway 是两个进程环境。手动测试前需要：

```bash
set -a
source /etc/hotel-ota-ai/hotel-ota.env
set +a
```

Gateway 生效则需要 user service drop-in 读取同一份 env，并重启 `openclaw-gateway.service`。

预期效果：

- `snapshot` 使用 `operating_snapshot` 返回真实房态、出租率、ADR、RevPAR。
- `baseline` 使用 `daily_metrics/monthly_metrics` 修正目标和小时曲线。
- `deviation` 使用数据库实际间夜/已售房计算完成率。
- `revenue-decision` 使用 `operating_snapshot + price_snapshot` 选择调价候选，仍只输出 dry-run 和审批要求。

如果 OpenClaw Gateway 是 `systemd user service`，不要把酒店项目环境变量写到 system service drop-in。应使用 `systemctl --user` 的 drop-in：

```bash
mkdir -p ~/.config/systemd/user/openclaw-gateway.service.d

cat > ~/.config/systemd/user/openclaw-gateway.service.d/10-hotel-ota-env.conf <<'EOF'
[Service]
EnvironmentFile=/etc/hotel-ota-ai/hotel-ota.env
WorkingDirectory=/opt/openclaw/workspaces/hotel-ota-ai
EOF

systemctl --user daemon-reload
systemctl --user restart openclaw-gateway.service
systemctl --user status openclaw-gateway.service --no-pager
```

确认 drop-in 生效：

```bash
systemctl --user cat openclaw-gateway.service
systemctl --user show openclaw-gateway.service -p FragmentPath -p DropInPaths
journalctl --user -u openclaw-gateway.service -n 100 --no-pager
```

如果 Gateway 不是 `root` 的 user service，而是普通用户运行，必须让该用户能读取 `/etc/hotel-ota-ai/hotel-ota.env` 和 `/etc/hotel-ota-ai/feishu-role-map.json`，并能写入 `/var/lib/hotel-ota-ai`、`/var/log/hotel-ota-ai`。

服务器上可以只检查开关和字段是否存在，不要把真实密钥贴到聊天或日志里：

```bash
grep -E "ENABLE_LIVE|BASE_URL|APP_KEY|TOKEN|SIGN_KEY" .env
```

## 4. 初始化运行时数据库

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
.venv/bin/python runtime/hotel_ota_runtime.py init-db
.venv/bin/python runtime/hotel_ota_runtime.py seed-demo
```

检查 dry-run：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py baseline --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py deviation --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template operating_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template price_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template order_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode columns --table fact_daily_metrics
```

P2 蓝图命令可先做 dry-run 验证：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py competition-alert --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py promotion-plan --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py promotion-roi --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py promotion-execute --hotel-id puyue
```

## 5. 配置 OpenClaw workspace

确认目录结构：

```bash
/opt/openclaw/workspaces/hotel-ota-ai/AGENTS.md
/opt/openclaw/workspaces/hotel-ota-ai/TOOLS.md
/opt/openclaw/workspaces/hotel-ota-ai/BOOTSTRAP.md
/opt/openclaw/workspaces/hotel-ota-ai/skills/hotel-ota/s01-control-config/SKILL.md
/opt/openclaw/workspaces/hotel-ota-ai/skills/hotel-ota/s17-customer-order-analysis/SKILL.md
```

OpenClaw 会在 workspace `skills/` 下发现 `SKILL.md`。如果当前工作区不是该目录，请在 OpenClaw agent/workspace 配置中指向：

```bash
/opt/openclaw/workspaces/hotel-ota-ai
```

当前阿里云服务器已验证的配置方式是让默认 `main` agent 指向项目 workspace：

```bash
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.$(date +%F_%H%M%S)

openclaw config set agents.defaults.workspace '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config set agents.defaults.repoRoot '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config set agents.defaults.contextInjection '"always"' --strict-json --replace

openclaw gateway restart

openclaw config get agents.defaults.workspace
openclaw config get agents.defaults.repoRoot
openclaw config get agents.defaults.contextInjection
openclaw agents list
```

期望看到：

```text
main (default)
Workspace: /opt/openclaw/workspaces/hotel-ota-ai
```

将 `config/openclaw.example.json` 合并到 OpenClaw gateway 配置。推荐启用命名 agent：

```text
hotel-ota-chief
```

该 agent 会显式绑定 17 个酒店 skill，并通过 `AGENTS.md`、`TOOLS.md`、`BOOTSTRAP.md` 注入项目总控规则。若当前 OpenClaw 版本或服务器配置还没创建 `hotel-ota-chief`，先用默认 `main` 完成验收即可。

### 5.1 命名 Agent 配置失败时的降级处理

当前 OpenClaw 2026.5.28 实测，直接写入包含高级字段的 `agents.list` 可能报：

```text
Error: Config validation failed: agents.list.0: Invalid input
```

这表示本次写入没有成功，后续 `Config valid` 只是说明旧配置仍然有效。常见原因是当前版本 schema 不接受 `contextInjection`、`bootstrapMaxChars`、`bootstrapTotalMaxChars`、`skillsLimits`、`repoRoot` 等字段。

处理原则：先不要卡在命名 agent，先让默认 `main` agent 指向项目 workspace，并通过 `openclaw skills list/check` 看到 17 个 skill。

最小可用配置：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai

SKILLS='["s01-control-config","s02-operating-snapshot","s03-message-hub","s04-market-context","s05-revenue-decision","s06-price-sync-execution","s07-competitive-monitoring","s08-promotion-planning","s09-traffic-peak-valley","s10-roi-decision","s11-promotion-execution","s12-reputation-management","s13-review-reply","s14-operation-diagnosis","s15-sales-baseline","s16-progress-deviation","s17-customer-order-analysis"]'

openclaw config set agents.defaults.workspace '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config set agents.defaults.repoRoot '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config set agents.defaults.userTimezone '"Asia/Shanghai"' --strict-json --replace
openclaw config set agents.defaults.skills "$SKILLS" --strict-json --replace

openclaw config validate
openclaw gateway restart
openclaw skills list
openclaw skills check
```

如果仍然希望创建 `hotel-ota-chief`，先尝试只保留 `id`、`workspace`、`skills`：

```bash
AGENT='[{"id":"hotel-ota-chief","workspace":"/opt/openclaw/workspaces/hotel-ota-ai","skills":["s01-control-config","s02-operating-snapshot","s03-message-hub","s04-market-context","s05-revenue-decision","s06-price-sync-execution","s07-competitive-monitoring","s08-promotion-planning","s09-traffic-peak-valley","s10-roi-decision","s11-promotion-execution","s12-reputation-management","s13-review-reply","s14-operation-diagnosis","s15-sales-baseline","s16-progress-deviation","s17-customer-order-analysis"]}]'

openclaw config set agents.list "$AGENT" --strict-json --replace
openclaw config validate
openclaw skills list --agent hotel-ota-chief
openclaw skills check --agent hotel-ota-chief
```

如果最小版仍报 `agents.list.0: Invalid input`，本轮先删除命名 agent 配置诉求，只使用默认 `main`。只要默认 agent 能看到 17 个 skill，P0/P1 演示闭环不受影响。

检查 skill：

```bash
openclaw skills list
openclaw skills check
openclaw skills info s05-revenue-decision
openclaw skills list --agent hotel-ota-chief
openclaw skills check --agent hotel-ota-chief
openclaw skills info s05-revenue-decision --agent hotel-ota-chief
```

若没有看到 17 个 skill，检查：

- 当前工作区是否正确。
- `SKILL.md` frontmatter 是否存在 `name` 和 `description`。
- 每个 skill 是否存在 `references/input_schema.json`、`output_schema.json`、`rules.md`、`examples.md`、`runtime_commands.md`。
- Agent allowlist 是否包含这些 skill。
- 当前 OpenClaw CLI 是否支持 `--agent` 参数；若不支持，先用默认命令验证，并确认默认 agent 已读取 `agents.defaults.skills`。

如果执行：

```bash
openclaw config get agents.defaults.skills
```

返回：

```text
Config path not found: agents.defaults.skills
```

这不是错误，只表示当前没有配置 skill 白名单。只要 `openclaw skills check` 能看到 17 个酒店 skill 为 ready，就可以先按 workspace 自动发现方式验收。

Agent 命令要使用 `-m`：

```bash
openclaw agent --agent main -m "请读取 AGENTS.md、TOOLS.md、BOOTSTRAP.md，告诉我当前酒店 OTA 工程的 P0/P1 主线是什么。不要修改文件。"
```

不要写成：

```bash
openclaw agent "请读取 AGENTS.md ..."
```

否则会报 `Missing required option "-m, --message <text>"`。如果报 `No target session selected`，先显式加 `--agent main`。

### 5.2 模型配置建议

为了稳定验收，当前服务器建议默认使用可正常返回的模型，例如：

```bash
openclaw models set deepseek/deepseek-v4-flash
openclaw gateway restart
```

如果第三方模型返回：

```text
GatewayClientRequestError: FailoverError ... incomplete terminal response
INVALID_API_KEY
```

优先判断为模型供应商 API Key、鉴权或兼容性问题，不要误判为 skill、workspace 或 runtime 部署失败。第三方模型可以等 key 修复后用于离线优化文档和 skill，不建议在验收期直接作为默认 agent/cron 模型。

## 6. 配置飞书

执行登录向导：

```bash
openclaw channels login --channel feishu
openclaw gateway restart
```

建议配置：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "groupPolicy": "allowlist",
      "groupAllowFrom": ["oc_replace_with_project_group_id"],
      "requireMention": true,
      "streaming": true
    }
  }
}
```

飞书权限要分两层配置，二者不要互相替代：

- OpenClaw Gateway 层：`channels.feishu.groupAllowFrom`、`channels.feishu.allowFrom`、`groupPolicy`、`requireMention`。这层负责“哪些群和哪些入口可以进入 OpenClaw”。
- 酒店项目业务层：`/etc/hotel-ota-ai/feishu-role-map.json`。这层负责“进入后这个人是 admin、owner、operator、frontdesk 还是 guest，以及能做什么业务动作”。

推荐先配置 OpenClaw 入口层：

```bash
openclaw config set channels.feishu.groupPolicy '"allowlist"' --strict-json --replace
openclaw config set channels.feishu.groupAllowFrom '["oc_项目群ID"]' --strict-json --replace
openclaw config set channels.feishu.requireMention true --strict-json --replace
openclaw config set channels.feishu.dmPolicy '"allowlist"' --strict-json --replace
openclaw config set channels.feishu.allowFrom '["ou_admin用户ID","ou_owner用户ID"]' --strict-json --replace
openclaw config validate
openclaw gateway restart
```

这里的 `groupAllowFrom` 是群入口白名单；`allowFrom` 更适合限制私聊入口，保守做法是只放 `admin/owner`。

配置项目角色表：

```bash
mkdir -p /etc/hotel-ota-ai
cp /opt/openclaw/workspaces/hotel-ota-ai/config/feishu-role-map.example.json /etc/hotel-ota-ai/feishu-role-map.json
chmod 600 /etc/hotel-ota-ai/feishu-role-map.json
```

编辑 `/etc/hotel-ota-ai/feishu-role-map.json`，把 `allowed_chat_ids` 和 `users` 替换为真实飞书群 ID 与用户 ID。角色只能使用：

```text
admin
owner
operator
frontdesk
```

未在角色表中的发送人按 `guest` 处理：只返回无权限提示，不读取业务数据，不触发业务 skill。

两层权限都要配置的原因：

```text
只配 OpenClaw allowlist：机器人知道哪些群能进，但不知道谁是老板、运营、前台，业务审批不完整。
只配 feishu-role-map.json：业务层最终会阻断 guest，但未授权消息仍可能进入 Gateway/agent，浪费模型调用，也增加误触发风险。
```

权限 dry-run 验证：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id replace_with_operator_open_id --chat-id replace_with_project_group_id --skill s05-revenue-decision --action run_recommendation --auth-config /etc/hotel-ota-ai/feishu-role-map.json
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id unknown_open_id --chat-id replace_with_project_group_id --skill s02-operating-snapshot --action view_diagnosis --auth-config /etc/hotel-ota-ai/feishu-role-map.json
```

P0/P1 测试话术：

```text
@机器人 今天璞悦经营情况怎么样？
@机器人 做一次璞悦 OTA 运营诊断。
@机器人 给璞悦生成今日销售基准线。
@机器人 现在进度是否落后？原因是什么？
@机器人 今天璞悦需要调价吗？只给 dry-run 建议。
@机器人 预览执行 KING 房型 Mtop 今天平日价159、周末价189，不要真实执行。
```

## 7. 配置定时任务

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
bash cron/setup-cron.sh
openclaw cron list
openclaw cron runs --id <job-id> --limit 5
```

计划任务：

- S2 每小时第 7 分钟采集经营快照。
- S15 每天 07:30 生成销售基准线。
- S16 每小时第 12 分钟偏差诊断。
- S14 每周一 09:00 周诊断。

当前阿里云服务器实测 `openclaw cron add` 可能反复报：

```text
scope upgrade pending approval
pairing required: device is asking for more scopes than currently approved
```

这说明 Gateway 本地 device pairing 仍停在较低权限，例如只有 `operator.write`，但 cron 创建需要更高 scope。这个问题不影响 skill、runtime、agent 的基本验收；不要反复执行 `cron add` 生成新的 requestId。

如果短期需要定时跑业务任务，先使用 Linux `crontab` 兜底：

```bash
crontab -e
```

加入：

```cron
7 * * * * cd /opt/openclaw/workspaces/hotel-ota-ai && /opt/openclaw/workspaces/hotel-ota-ai/.venv/bin/python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue >> /var/log/hotel-ota-ai/snapshot.log 2>&1
30 7 * * * cd /opt/openclaw/workspaces/hotel-ota-ai && /opt/openclaw/workspaces/hotel-ota-ai/.venv/bin/python runtime/hotel_ota_runtime.py baseline --hotel-id puyue >> /var/log/hotel-ota-ai/baseline.log 2>&1
12 * * * * cd /opt/openclaw/workspaces/hotel-ota-ai && /opt/openclaw/workspaces/hotel-ota-ai/.venv/bin/python runtime/hotel_ota_runtime.py deviation --hotel-id puyue >> /var/log/hotel-ota-ai/deviation.log 2>&1
0 9 * * 1 cd /opt/openclaw/workspaces/hotel-ota-ai && /opt/openclaw/workspaces/hotel-ota-ai/.venv/bin/python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue >> /var/log/hotel-ota-ai/weekly-revenue-decision.log 2>&1
```

启动并检查：

```bash
systemctl enable --now crond
systemctl status crond --no-pager -l
tail -50 /var/log/hotel-ota-ai/snapshot.log
```

长期目标仍是修复 OpenClaw Gateway device scope，让定时任务、运行历史、agent 会话都回到 OpenClaw 内统一管理。

## 8. 渠道 API dry-run 验证

美团、Beyondh、订单来了 API 和数据库来源当前都只作为参考入口，具体接口权限、密钥、字段、表结构和回调地址待确认。P0/P1 不要求 API 已正式授权，只要求 dry-run 请求可生成、数据库只读模板可跑、样例字段能进入统一数据契约。

房型查询 dry-run：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py adapter-request \
  --hotel-id puyue \
  --adapter beyondh \
  --method Hotel.GetOrgRoomTypes \
  --biz-content '{"OrgId":"替换为真实OrgId","RoomTypeId":""}'
```

美团房价请求 dry-run：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py adapter-request \
  --hotel-id puyue \
  --adapter meituan \
  --path /pms/priceinve/getRoomPrice \
  --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
```

订单来了房价请求 dry-run：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py adapter-request \
  --hotel-id puyue \
  --adapter dindanll \
  --path /open/pms/third/ari/price \
  --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
```

样例归一化：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-price
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory
.venv/bin/python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
```

数据库来源只读验证：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template operating_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template price_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template order_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode columns --table fact_daily_metrics
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode sample --table fact_room_fee_daily --limit 5
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template price_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template order_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template daily_metrics --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template monthly_metrics --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind postgres --template operating_snapshot --hotel-id puyue
```

MySQL 未安装 `pymysql` 时返回 `blocked/missing_driver` 属于预期；连接成功但缺少 `/etc/hotel-ota-ai/database-source.json` 或 profile 时返回 `blocked/database_mapping_required`。PostgreSQL 仍作为 V2 预留。未知模板或自由 SQL 必须阻断。

调价 dry-run：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py execute-price \
  --hotel-id puyue \
  --room-type-id KING \
  --channel Mtop \
  --normal-price 159 \
  --weekend-price 189 \
  --begin-date 2026-06-01 \
  --end-date 2026-06-01 \
  --approved-by 老板姓名 \
  --dry-run
```

真实执行前检查：

- admin/owner 已确认。
- 价格没有低于底价。
- 单次涨降幅没有超过 S1 配置。
- 对应渠道 live 开关已开启，例如 `BEYONDH_ENABLE_LIVE=1`。
- 飞书消息已保留审批记录。

## 9. 先验收 P0/P1，再启用 P2

2026-06-15 前只认这条主线：

```text
总控配置 -> S2 经营快照 -> S14 运营诊断 -> S15 基准线 -> S16 偏差诊断 -> S5 收益建议 -> S6 调价 dry-run
```

P2 的 S7-S13/S17 可以保持可加载、可触发、可说明，但不要为了真实竞品采集、美团活动/推广执行、评论发布拖慢 P0/P1。

## 10. 用 OpenClaw 辅助继续完善 skill

推荐先使用统一适配提示词：

```text
请读取 requirements/OpenClaw自动适配提示词.md，并按其中规则自动检查和适配整个酒店 OTA AI 数字员工工程包。
```

在 OpenClaw 对话中使用：

```text
请读取 requirements/skill_specs.yaml 和 skills/hotel-ota/_shared/common-contract.md，
补充 s05-revenue-decision 的房价决策细则，但不得改变审批安全规则。
```

每次修改后执行：

```bash
openclaw skills check
openclaw gateway restart
```

建议用新会话验证，因为 OpenClaw 可能对 session 的 skill 列表做快照。

## 11. 上线检查表

- 17 个 skill 均可被 `openclaw skills list` 发现。
- P0/P1 的 9 个 skill 全部通过 `requirements/P0P1交付清单.md`。
- 飞书私信、群聊 @ 机器人均可用。
- 无 @ 时群聊不回复。
- 飞书角色表已生效，未授权用户按 `guest` 阻断。
- Runtime dry-run 输出正常。
- 渠道 API 统一策略已生效，API 未确定时不阻塞 P0/P1。
- Beyondh、美团、订单来了参考请求摘要可生成，且日志中已脱敏。
- 美团、订单来了样例字段可归一化到统一数据契约。
- 数据库只读来源可通过 `database-inspect` 探测、通过配置化 `database-query` 进入统一数据契约，且不会执行自由 SQL。
- OpenClaw cron 四个任务已创建；若 Gateway scope 尚未修复，则 Linux crontab 四个兜底任务已创建并有日志输出。
- 真实写接口仍默认关闭，除非完成 `admin/owner` 审批和安全检查。

## 12. 旧服务器更新流程

适用于服务器已经存在：

```bash
/opt/openclaw/workspaces/hotel-ota-ai
```

且 OpenClaw 已经能识别 17 个酒店 skill 的情况。

### 12.1 本地生成更新包

在 Windows 本地 PowerShell 中执行，排除运行数据和虚拟环境：

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$zip = "D:\hotel\openclaw-hotel-ota-ai-server-update-$stamp.zip"
$exclude = @('data','logs','.venv','__pycache__')
Push-Location D:\hotel\openclaw-hotel-ota-ai
Get-ChildItem -Force | Where-Object { $exclude -notcontains $_.Name } | Compress-Archive -DestinationPath $zip -Force
Pop-Location
Get-Item $zip
```

上传到服务器：

```powershell
scp D:\hotel\openclaw-hotel-ota-ai-server-update-YYYYMMDD-HHMMSS.zip root@服务器IP:/tmp/
```

### 12.2 服务器备份

```bash
cd /opt/openclaw/workspaces

BACKUP="/root/hotel-ota-ai-backup-$(date +%F_%H%M%S).tgz"
tar -czf "$BACKUP" hotel-ota-ai
echo "backup: $BACKUP"
```

### 12.3 解压更新包

Windows 生成的 zip 可能出现：

```text
appears to use backslashes as path separators
```

这是因为 zip 内路径用了 Windows 反斜杠。不要直接信任 `unzip` 的目录结构，推荐用 Python 解压并把 `\` 转成 `/`：

```bash
rm -rf /tmp/hotel-ota-ai-update
mkdir -p /tmp/hotel-ota-ai-update

python3.11 - <<'PY'
import zipfile
from pathlib import Path

zip_path = Path("/tmp/openclaw-hotel-ota-ai-server-update-YYYYMMDD-HHMMSS.zip")
out_dir = Path("/tmp/hotel-ota-ai-update")

with zipfile.ZipFile(zip_path) as z:
    for item in z.infolist():
        name = item.filename.replace("\\", "/").lstrip("/")
        if not name or name.endswith("/"):
            continue
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(item) as src, open(target, "wb") as dst:
            dst.write(src.read())
PY
```

把 `YYYYMMDD-HHMMSS` 换成真实文件名。

检查解压结构：

```bash
find /tmp/hotel-ota-ai-update -maxdepth 2 -type f | head -40
ls -la /tmp/hotel-ota-ai-update
```

正常应该看到：

```text
AGENTS.md
TOOLS.md
BOOTSTRAP.md
runtime/
skills/
requirements/
config/
cron/
```

### 12.4 覆盖 workspace

如果服务器没有 `rsync`，不要卡在安装工具上；直接用 `/bin/cp`。必须写 `/bin/cp`，避免 `cp` 被 alias 成交互模式导致一直问“是否覆盖”。

```bash
/bin/cp -a /tmp/hotel-ota-ai-update/. /opt/openclaw/workspaces/hotel-ota-ai/
chmod -R 755 /opt/openclaw/workspaces/hotel-ota-ai
```

不要复制粘贴成一行连在一起；每条命令单独执行。尤其不要出现：

```text
openclaw skills check.venv/bin/python ...
```

这种是两条命令粘连，不是 OpenClaw 或 runtime 错误。

### 12.5 验证更新结果

进入 workspace：

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
```

检查 runtime 模块化结构：

```bash
ls runtime
```

应看到：

```text
adapters  decisions  safety  cli.py  common.py  contracts.py  storage.py
```

检查 17 个 skill references：

```bash
find skills/hotel-ota -path '*/references/input_schema.json' | wc -l
find skills/hotel-ota -path '*/references/output_schema.json' | wc -l
find skills/hotel-ota -path '*/references/rules.md' | wc -l
find skills/hotel-ota -path '*/references/examples.md' | wc -l
find skills/hotel-ota -path '*/references/runtime_commands.md' | wc -l
```

五个结果都应该是：

```text
17
```

检查 runtime 新命令：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py --help
.venv/bin/python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py competition-alert --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py execute-price --hotel-id puyue --room-type-id KING --normal-price 159 --begin-date 2026-06-02 --end-date 2026-06-02 --approved-by boss --dry-run --no-log
```

如果 `.venv/bin/python` 不存在，改用：

```bash
python3.11 runtime/hotel_ota_runtime.py --help
```

检查 OpenClaw：

```bash
openclaw skills list
openclaw skills check
openclaw skills info s05-revenue-decision
```

可选：重启 gateway，让新 bootstrap 和 skill 内容在新会话中稳定生效：

```bash
openclaw gateway restart
```

### 12.6 更新成功标准

- `runtime/hotel_ota_runtime.py --help` 能看到 `demand-index`、`ota-health`、`conversion-diagnosis` 等新命令。
- `demand-index` 和 `ota-health` 返回 JSON。
- 17 个 skill 的五类 reference 文件计数都是 17。
- `openclaw skills check` 无 missing requirements。
- 17 个酒店 skill 显示为 ready and visible。

### 12.7 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `rsync: 未找到命令` | 服务器没有安装 rsync | 用 `/bin/cp -a /tmp/hotel-ota-ai-update/. /opt/openclaw/workspaces/hotel-ota-ai/` |
| `cp：是否覆盖...` | `cp` 被 alias 成交互模式 | 使用 `/bin/cp`，不要用裸 `cp` |
| `unzip` 提示反斜杠路径 | Windows zip 路径分隔符 | 用 Python 解压脚本把 `\` 转成 `/` |
| `invalid choice: demand-index` | runtime 没覆盖成功，仍是旧入口 | 重新执行 `/bin/cp -a ...` 并检查 `ls runtime` |
| `openclaw skills check.venv/bin/python` | 两条命令粘连 | 分行重新执行 |
| OpenClaw cron 仍报 scope/pairing | Gateway device scope 问题 | 不影响本轮更新；短期用 Linux crontab 兜底 |

## 13. 服务器实测常见问题总表

## 13.0 系统服务版 Gateway 与本地 embedding 记忆

当前服务器如果已经改为 system service，请使用：

```bash
systemctl restart openclaw-gateway.service
systemctl status openclaw-gateway.service --no-pager -l
journalctl -u openclaw-gateway.service -n 100 --no-pager
```

不要再使用：

```bash
systemctl --user restart openclaw-gateway.service
openclaw gateway restart
```

这两个命令会走 user service/user bus，在 root SSH 会话里可能报 `Failed to connect to bus: No medium found`。

### 13.0.1 确认系统服务文件

```bash
cat /etc/systemd/system/openclaw-gateway.service
```

推荐内容：

```ini
[Unit]
Description=OpenClaw Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/openclaw/workspaces/hotel-ota-ai
Environment=HOME=/root
EnvironmentFile=/etc/hotel-ota-ai/hotel-ota.env
ExecStart=/usr/local/bin/openclaw gateway --port 18789
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

服务修改后执行：

```bash
systemctl daemon-reload
systemctl enable --now openclaw-gateway.service
systemctl restart openclaw-gateway.service
ss -ltnp | grep 18789
```

### 13.0.2 配置本地 embedding memorySearch

本项目推荐先使用本地 embedding，不依赖外部 API key。它只用于上下文召回，不能参与授权、审批、角色识别、live 执行或业务事实判断。

跨会话记忆的归档、禁记内容、验收话术和服务器私有目录见 `requirements/数字员工长期记忆与归档规范.md`。仅运行 GGUF 不等于跨会话记忆生效；必须确认 OpenClaw memorySearch 启用、索引成功，并且有脱敏归档内容可检索。

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai

openclaw config set agents.defaults.memorySearch.enabled true --strict-json --replace
openclaw config set agents.defaults.memorySearch.provider '"local"' --strict-json --replace
openclaw config set agents.defaults.memorySearch.cache.enabled true --strict-json --replace
openclaw config set agents.defaults.memorySearch.sync.embeddingBatchTimeoutSeconds 900 --strict-json --replace
openclaw config validate
```

项目根目录应存在：

```bash
/opt/openclaw/workspaces/hotel-ota-ai/MEMORY.md
```

`MEMORY.md` 只记录项目长期规则、部署坑、数据源状态、skill 测试结论。不得记录 API key、数据库 DSN、密码、token、真实飞书 ID、审批凭证、客户姓名、房号、订单号。

重启系统服务：

```bash
systemctl restart openclaw-gateway.service
systemctl status openclaw-gateway.service --no-pager -l
```

首次建立索引可能会下载本地 embedding 模型，耗时较长：

```bash
openclaw memory status --deep --agent main
openclaw memory index --force --agent main
openclaw memory search "飞书权限 数据新鲜度 cron"
openclaw memory search "旧数据不能发今日快报"
openclaw memory search "飞书输出订单明细应该怎么处理"
```

如果下载或索引卡住，先看 Gateway 日志：

```bash
journalctl -u openclaw-gateway.service -n 200 --no-pager
```

### 13.0.3 memory 使用边界

- 可以记：项目规则、服务器部署坑、长期业务决策、skill 测试结论、数据源状态。
- 不得记：密钥、DSN、真实飞书 ID、客户隐私、审批凭证。
- 权限仍只认 `/etc/hotel-ota-ai/feishu-role-map.json` 和 runtime `auth_context`。
- 数据事实仍只认 runtime、数据库、API、人工上传或 RPA 返回。
- 审批仍只认 approval/runtime/live 开关。

| 现象 | 判断 | 处理 |
| --- | --- | --- |
| `Python 3.6.8` | 系统 Python 太旧 | 安装 `python3.11`，用 `python3.11 -m venv .venv` 重建虚拟环境 |
| `.venv/bin/python` 不存在 | 旧部署未建 Python 3.11 venv | 回到第 2.1 节重建 `.venv` |
| 工程目录多了一层 `openclaw-hotel-ota-ai/` | 上传包解压后未展开到 workspace 根 | 用 `find openclaw-hotel-ota-ai -mindepth 1 -maxdepth 1 -exec mv -t . {} +` |
| `mv openclaw-hotel-ota-ai/.* .` 卡住或异常 | `.*` 可能匹配特殊目录 | 不再使用该命令，按第 1 节安全移动 |
| `Config path not found: agents.defaults.skills` | 未配置 skill 白名单 | 不一定是错；只要 `openclaw skills check` 能看到 17 个 skill ready，就先验收 |
| `agents.list.0: Invalid input` | 当前 OpenClaw schema 不接受命名 agent 的高级字段 | 先用第 5.1 节最小配置，只设置默认 workspace 和 17 个 skill；命名 agent 后置 |
| `openclaw skills list/check` 看不到 17 个 skill | 命令不在项目 workspace、目录多套一层、默认 agent 没指向 workspace 或 allowlist 未配置 | 进入 `/opt/openclaw/workspaces/hotel-ota-ai`，检查 `find skills -name SKILL.md | wc -l`，再设置 `agents.defaults.workspace` |
| `Missing required option "-m, --message <text>"` | `openclaw agent` 少了消息参数 | 使用 `openclaw agent --agent main -m "问题"` |
| `No target session selected` | 没指定目标 agent/session | 加 `--agent main` |
| Gateway 是 `systemd user service`，但环境变量不生效 | 把 drop-in 写到了 system service，或用了 `systemctl restart` | 使用 `~/.config/systemd/user/openclaw-gateway.service.d/` 和 `systemctl --user daemon-reload/restart` |
| `EnvironmentFile` 已配置但 runtime 仍读不到角色表 | Gateway 运行用户没有权限读取 `/etc/hotel-ota-ai` | 确认 Gateway user service 的运行用户，并授予 env、角色表、数据目录、日志目录读写权限 |
| 已配 `/etc/hotel-ota-ai/feishu-role-map.json` 但非项目群仍能进 OpenClaw | 只配了业务角色表，没配 Gateway 入口白名单 | 同时配置 `channels.feishu.groupPolicy=allowlist`、`groupAllowFrom`、`requireMention=true` |
| 已配 `channels.feishu.groupAllowFrom` 但无法区分老板、运营、前台 | 只配了 OpenClaw 入口层，没配业务角色表 | 同时配置 `/etc/hotel-ota-ai/feishu-role-map.json` 的 `allowed_chat_ids` 和 `users` |
| `incomplete terminal response` | 第三方模型流式响应异常或 provider 不兼容 | 先切换到 `deepseek/deepseek-v4-flash` 验收 |
| `INVALID_API_KEY` | 第三方模型 API Key 无效、过期或权限不对 | 修复供应商 key；不要误判为 skill 部署失败 |
| `scope upgrade pending approval` | Gateway device token scope 不够 | 不反复 `cron add`；短期用 Linux crontab，长期清理或修复 device pairing |
| `gateway token mismatch` | `remote.token` 与 Gateway 实际 token 不一致 | 同步 token 或重启/重装 Gateway 前先备份 `~/.openclaw` |
| `--token "$AUTH_TOKEN": 未找到命令` | 把参数当成独立命令执行了 | `--token` 必须接在 `openclaw` 命令后 |
| `rsync: 未找到命令` | 服务器未装 rsync | 用 `/bin/cp -a` 覆盖更新 |
| `cp：是否覆盖...` | `cp` 被 alias 成交互模式 | 使用 `/bin/cp` |
| `unzip` 提示 backslashes | Windows zip 使用反斜杠路径 | 用第 12.3 节 Python 解压脚本 |
| 新命令不在 `--help` 中 | 更新包没覆盖 runtime | 重新 `/bin/cp -a`，检查 `runtime/cli.py` 和 `runtime/decisions/` |
| `openclaw skills check` 通过但新对话没读到新规则 | 旧会话缓存 skill/context | 重启 Gateway，并用新会话验证 |

## 14. 当前服务器状态记录

截至 2026-06-02，根据 `D:\hotel\openclaw_hotel_ota_ai_deployment_notes.md`：

- `/opt/openclaw/workspaces/hotel-ota-ai` 已是正确 workspace。
- Python 3.11.13 `.venv` 已可用。
- `init-db`、`seed-demo`、P0/P1 runtime dry-run 已通过。
- 17 个酒店 OTA skill 已被 OpenClaw 识别，`s01` 到 `s17` 为 ready。
- `s05-revenue-decision` 单独检查通过。
- 旧服务器更新已验证可用 `/bin/cp -a` 替代缺失的 `rsync`。
- OpenClaw cron 仍需处理 Gateway device scope/pairing；短期以 Linux crontab 兜底。

如果后续服务器状态变化，先更新部署记录，再同步更新本教程。
