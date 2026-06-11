# runtime 模块化说明

## 1. 入口兼容

OpenClaw、skill、cron 和飞书仍统一调用：

```bash
python runtime/hotel_ota_runtime.py ...
```

`hotel_ota_runtime.py` 只是兼容入口，实际逻辑在 `runtime/` 包内。

## 2. 模块职责

| 模块 | 职责 |
| --- | --- |
| `runtime/cli.py` | CLI 命令路由 |
| `runtime/common.py` | 时间、JSON/base64 输入、输出、脱敏 |
| `runtime/contracts.py` | 统一数据契约和输出 envelope |
| `runtime/storage.py` | SQLite、日志、审批记录、demo 数据 |
| `runtime/adapters/beyondh.py` | Beyondh 请求构造、签名、dry-run/live 保护 |
| `runtime/adapters/meituan.py` | 美团请求构造和样例归一化 |
| `runtime/adapters/dindanll.py` | 订单来了请求构造、状态枚举、样例归一化 |
| `runtime/safety/guards.py` | 价格底线、涨降幅、live 开关 |
| `runtime/safety/approvals.py` | 审批闸口 |
| `runtime/decisions/demand.py` | 需求指数和经营快照 |
| `runtime/decisions/pricing.py` | 收益建议和调价 dry-run |
| `runtime/decisions/ota_health.py` | OTA 健康和流量转化诊断 |
| `runtime/decisions/promotion.py` | 活动建议、ROI、推广执行 dry-run |
| `runtime/decisions/competition.py` | 竞对预警 |
| `runtime/decisions/tasks.py` | 前台执行清单 |
| `runtime/decisions/reputation.py` | 评论分类、升级和回复草稿 |

## 3. 新增命令

```bash
python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue
python runtime/hotel_ota_runtime.py ota-health --hotel-id puyue
python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue
python runtime/hotel_ota_runtime.py competition-alert --hotel-id puyue
python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id puyue
python runtime/hotel_ota_runtime.py reputation-diagnosis --hotel-id puyue
python runtime/hotel_ota_runtime.py promotion-plan --hotel-id puyue
python runtime/hotel_ota_runtime.py promotion-roi --hotel-id puyue
python runtime/hotel_ota_runtime.py promotion-execute --hotel-id puyue
```

## 4. 禁止事项

- skill 不直接 import runtime 内部模块。
- skill 不直接解释原始 API 状态码。
- 真实写动作不得绕过审批、dry-run、安全校验和 live 开关。
