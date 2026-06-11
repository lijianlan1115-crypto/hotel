# OpenClaw 常用配置命令

## 0. 稳定性排障速查

飞书身份测试优先使用 `--open-id`：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id ou_admin用户ID --chat-id oc_项目群ID --skill s02-operating-snapshot --action view_diagnosis --auth-config /etc/hotel-ota-ai/feishu-role-map.json
```

如果误用 `--user-id ou_...`，runtime 会兼容兜底，但输出里应出现 `identity_warning`，说明配置或调用示例需要改回 `--open-id`：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --user-id ou_admin用户ID --chat-id oc_项目群ID --skill s02-operating-snapshot --action view_diagnosis --auth-config /etc/hotel-ota-ai/feishu-role-map.json
```

检查数据库是否有今日数据：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
```

输出中重点看 `data_business_date`、`data_snapshot_time`、`data_age_hours`、`freshness_status`。只有 `freshness_status=fresh` 才能按今日快报或真实调价前置证据使用。

Cron 报 `Request was aborted` 时先看日志，不要直接补造快报：

```bash
openclaw cron list
openclaw cron runs --id <job-id> --limit 5
journalctl --user -u openclaw-gateway.service -n 200 --no-pager
cat ~/.openclaw/logs/gateway-restart.log
```

Memory/embedding 只做上下文召回。检查或配置 memory 时，不得写入密钥、DSN、真实飞书 ID、审批凭证、客户隐私；权限仍只认 `/etc/hotel-ota-ai/feishu-role-map.json`。

本文件用于服务器日常配置和排障。真实密钥、DSN、飞书用户 ID、群 ID 只写服务器私有文件，不提交 GitHub。

## 1. 工作目录

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
git status --short
```

服务器以 GitHub `origin/main` 为代码标准：

```bash
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 pull
```

如果 GitHub 网络不稳定，先测试：

```bash
curl -I https://github.com --connect-timeout 10
git ls-remote https://github.com/TAI-YE-1/hotel--ota-ai.git HEAD
```

## 2. Gateway 环境变量

私有 env 文件：

```bash
nano /etc/hotel-ota-ai/hotel-ota.env
chmod 600 /etc/hotel-ota-ai/hotel-ota.env
```

常用字段：

```bash
HOTEL_OTA_DB=/var/lib/hotel-ota-ai/hotel_ops.sqlite
HOTEL_OTA_LOG_DIR=/var/log/hotel-ota-ai
HOTEL_OTA_AUTH_CONFIG=/etc/hotel-ota-ai/feishu-role-map.json

HOTEL_OTA_DB_SOURCE_ENABLE=1
HOTEL_OTA_DB_KIND=mysql
HOTEL_OTA_DB_PROFILE=report_mysql_prod
HOTEL_OTA_DB_DSN=mysql://user:password@host:3306/dbname?charset=utf8mb4
HOTEL_OTA_DB_READONLY=1
HOTEL_OTA_DB_MAPPING_CONFIG=/etc/hotel-ota-ai/database-source.json

BEYONDH_ENABLE_LIVE=0
MEITUAN_ENABLE_LIVE=0
DINDANLL_ENABLE_LIVE=0
```

手动 shell 测试前加载 env：

```bash
set -a
source /etc/hotel-ota-ai/hotel-ota.env
set +a
```

OpenClaw Gateway 是 systemd user service 时，配置 drop-in：

```bash
mkdir -p ~/.config/systemd/user/openclaw-gateway.service.d

cat > ~/.config/systemd/user/openclaw-gateway.service.d/10-hotel-ota-env.conf <<'EOF'
[Service]
EnvironmentFile=/etc/hotel-ota-ai/hotel-ota.env
WorkingDirectory=/opt/openclaw/workspaces/hotel-ota-ai
EOF

systemctl --user daemon-reload
systemctl --user restart openclaw-gateway.service
openclaw gateway status
```

检查 drop-in：

```bash
systemctl --user cat openclaw-gateway.service
systemctl --user show openclaw-gateway.service -p DropInPaths
journalctl --user -u openclaw-gateway.service -n 100 --no-pager
```

## 3. 飞书入口权限

飞书权限分两层。

OpenClaw Gateway 层负责“哪些群和入口能进 OpenClaw”：

```bash
openclaw config set channels.feishu.groupPolicy '"allowlist"' --strict-json --replace
openclaw config set channels.feishu.groupAllowFrom '["oc_项目群ID"]' --strict-json --replace
openclaw config set channels.feishu.requireMention true --strict-json --replace
openclaw config set channels.feishu.dmPolicy '"allowlist"' --strict-json --replace
openclaw config set channels.feishu.allowFrom '["ou_admin用户ID","ou_owner用户ID"]' --strict-json --replace
openclaw config validate
openclaw gateway restart
```

酒店项目角色表负责“进来以后能做什么”：

```bash
cp config/feishu-role-map.example.json /etc/hotel-ota-ai/feishu-role-map.json
nano /etc/hotel-ota-ai/feishu-role-map.json
chmod 600 /etc/hotel-ota-ai/feishu-role-map.json
```

角色含义：

```text
admin      超级管理员，可管理角色、安全配置、审批和紧急停用
owner      老板，可查看全部业务结果并审批真实执行
operator   运营，可诊断、建议、dry-run、发起审批
frontdesk  前台，只能接收任务、上传反馈
guest      未授权用户，默认阻断
```

角色表示例：

```json
{
  "allowed_chat_ids": ["oc_项目群ID"],
  "users": [
    {"open_id": "ou_admin用户ID", "role": "admin"},
    {"open_id": "ou_owner用户ID", "role": "owner"},
    {"open_id": "ou_operator用户ID", "role": "operator"},
    {"open_id": "ou_frontdesk用户ID", "role": "frontdesk"}
  ]
}
```

权限测试：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id ou_operator用户ID --chat-id oc_项目群ID --skill s02-operating-snapshot --action view_diagnosis
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id ou_frontdesk用户ID --chat-id oc_项目群ID --skill s05-revenue-decision --action create_dry_run
.venv/bin/python runtime/hotel_ota_runtime.py auth-check --source feishu --open-id ou_owner用户ID --chat-id oc_项目群ID --skill s06-price-sync-execution --action approve_live_action
```

## 4. MySQL 报表库配置

复制映射样例：

```bash
cp config/database-source.example.json /etc/hotel-ota-ai/database-source.json
nano /etc/hotel-ota-ai/database-source.json
chmod 600 /etc/hotel-ota-ai/database-source.json
```

安装驱动：

```bash
.venv/bin/python -m pip install pymysql
```

探测：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode columns --table fact_daily_metrics
.venv/bin/python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode sample --table fact_room_fee_daily --limit 5
```

查询模板：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template price_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template order_snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template daily_metrics --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template monthly_metrics --hotel-id puyue
```

主链路数据库优先验证：

```bash
.venv/bin/python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py baseline --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py deviation --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue
.venv/bin/python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
```

## 5. OpenClaw Skill 与 Agent

检查 17 个 skill：

```bash
find skills -name SKILL.md | wc -l
openclaw skills list
openclaw skills check
```

如果命名 agent 不兼容，先用默认 workspace：

```bash
openclaw config set agents.defaults.workspace '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config set agents.defaults.repoRoot '"/opt/openclaw/workspaces/hotel-ota-ai"' --strict-json --replace
openclaw config validate
openclaw gateway restart
```

Agent 测试：

```bash
openclaw agent -m "请读取 requirements/OpenClaw总控Agent提示词.md，并说明 P0/P1 如何运行。不要修改文件。"
```

## 6. 常见排障

GitHub 拉取卡住：

```bash
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 pull
```

本地 runtime 找不到 env：

```bash
set -a
source /etc/hotel-ota-ai/hotel-ota.env
set +a
```

MySQL 返回 `database_mapping_required`：

```bash
echo "$HOTEL_OTA_DB_PROFILE"
echo "$HOTEL_OTA_DB_MAPPING_CONFIG"
ls -l /etc/hotel-ota-ai/database-source.json
```

Gateway 运行但端口未监听：

```bash
journalctl --user -u openclaw-gateway.service -n 200 --no-pager
cat ~/.openclaw/logs/gateway-restart.log
```

服务器只忽略 `.openclaw/`：

```bash
grep -qxF '.openclaw/' .git/info/exclude || echo '.openclaw/' >> .git/info/exclude
```
