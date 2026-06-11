# Feishu Routing Contract

This Skill does not listen to Feishu directly. The Feishu entry service or
OpenClaw Agent must use `config/triggers.yaml` to decide whether a message
routes to S14.

## Required Behavior

1. Read `config/triggers.yaml`.
2. If the message contains any `trigger_phrases`, route to this Skill.
3. Extract only control inputs:
   - `hotel_id`
   - `platform`
   - `period_start`
   - `period_end`
   - optional display/output fields
4. Call:

```python
S14OperationDiagnosis(config).execute(inputs)
```

5. Send **only** the fixed Feishu text produced by `runtime/reply_formatter.py`. Do
   not generate, rewrite, or supplement the message in the entry service.

## 飞书输出格式：必须固定（强制约束）

飞书 Bot / OpenClaw Agent / 任何中间层都**不得**自行拼接飞书文本。飞书最终
回复必须由 `runtime/reply_formatter.py` 单一来源生成。

### 唯一允许的链路

```text
Agent / 大模型只输出 JSON 对象
  ↓
Python 端 json.loads(agent_output)
  ↓
合法 JSON → runtime/reply_formatter.py::format_agent_json_output
           → runtime/reply_formatter.py::format_feishu_message(data)
  ↓
Python 用 send_text(open_id, reply) 把固定模板文本发到飞书
  ↓
非法 JSON / 缺字段 → 返回"诊断结果格式异常，请重新生成。"
```

### 飞书固定模板（不可改）

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

### 强制规则（写死）

- 必须使用 `runtime/reply_formatter.py::format_feishu_message` 或
  `runtime/feishu_adapter.py::build_feishu_reply` / `build_feishu_reply_from_agent_output`。
- 必须保留上面 6 段（标题、空行、酒店/周期/得分/风险、空行、报告链接、空行、说明），
  一段都不能多、一段都不能少。
- 禁止 Bot / Agent 在飞书消息中加 emoji 列表、模块得分清单、风险描述、行动建议。
- 禁止 Bot / Agent 自行生成"飞猪诊断：xx/100 中风险 | ..."这种自定义开头。
- 禁止 Bot / Agent 修改 `final_score` / `risk_text` / `report_url` 任意一个字符。
- 禁止把 deepseek / qwen / gpt 等大模型原文（Markdown / 表格 / 自然语言）作为
  飞书消息发送。
- 禁止在 Feishu Bot 代码里再写一份格式化函数或模板字符串。

### Agent JSON 契约（不可改）

- 必须是合法 JSON 对象。
- 不得包含 Markdown、代码块、解释文字、emoji 列表。
- 最少字段：`hotel_name`、`period_start`、`period_end`、`final_score`、`report_url`。
- 解析失败 → `诊断结果格式异常，请重新生成。`（不允许 Bot 自行补字段、猜分数）。

### 正确示例

```python
# 方式 A：Agent 输出 JSON → Python 固定排版（推荐）
from runtime.feishu_adapter import build_feishu_reply_from_agent_output

agent_output = call_s14_agent(inputs)  # 必须是 JSON 字符串
reply = build_feishu_reply_from_agent_output(agent_output)
send_text(open_id, reply)

# 方式 B：直接走 S14 Skill（更稳）
from runtime import S14OperationDiagnosis
from runtime.feishu_adapter import build_feishu_reply

result = S14OperationDiagnosis(config).execute(inputs)
reply = build_feishu_reply(result)  # 内部用 result["feishu_message"]
send_text(open_id, reply)
```

### 错误示例（禁止使用）

```python
# 禁止：自己拼飞书文本
reply = f"飞猪诊断：{score}/100 {risk} | {problems}\n{url}"
send_text(open_id, reply)

# 禁止：把 Agent 原文直接发出去
reply = call_agent_text(inputs)  # 可能是 Markdown / 表格 / emoji
send_text(open_id, reply)

# 禁止：再写一份模板
TEMPLATE = "【S14】{hotel} 得分 {score} ..."
reply = TEMPLATE.format(hotel=name, score=score)
send_text(open_id, reply)
```

## Minimal Feishu Entry Example

```python
if should_route_to_s14(text):
    result = S14OperationDiagnosis(config).execute(inputs)
    send_text(open_id, result["feishu_message"])
```

## Current Local-Test Auto Trigger

当前本地验证阶段已经不需要人工手动执行命令。飞书 Bot/入口服务常驻运行，收到消息后自动调用：

```python
from runtime.feishu_adapter import handle_feishu_text_message

reply = handle_feishu_text_message(text)
if reply:
    send_text(open_id, reply)
```

`handle_feishu_text_message` 内部已经走 `format_feishu_message`，不再依赖 Agent
拼接文本；如 Bot 仍要直接调 Agent JSON 链路，必须使用
`build_feishu_reply_from_agent_output(agent_output)`。

用户侧链路：

```text
飞书发送：生成飞猪 S14 诊断
↓
飞书 Bot 收到 message 事件
↓
handle_feishu_text_message(text) 命中触发词
↓
后台自动运行 scripts/s14_local_report.py
↓
更新 ota_diagnosis_report_demo.html
↓
Python 用 format_feishu_message 生成固定飞书文本
↓
飞书回复【S14 酒店 OTA 诊断报告已生成】+ 6 段固定模板
```

注意：Python 不由飞书用户手动运行。Python 只是飞书 Bot 服务端的后台执行方式。后续接入 OpenClaw 正式运行时，把 `runtime/feishu_adapter.py` 中的 `run_s14_local_table_mode()` 替换为 `S14OperationDiagnosis(config).execute(inputs)` 即可。

## Forbidden

- Do not calculate score in the entry service.
- Do not build risk level in the entry service.
- Do not create a separate Feishu reply template in the entry service.
- Do not pass `metrics`, `business_fields`, `json_payload`, or upstream Skill output.
- Do not let the Agent (deepseek/qwen/gpt/...) output its own natural language /
  Markdown / emoji list to Feishu.
- Do not rewrite `final_score`, `risk_text`, `report_url`, or any field in
  `format_feishu_message` output.
