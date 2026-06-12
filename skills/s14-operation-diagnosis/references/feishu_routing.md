# Feishu Routing Contract

This Skill does not listen to Feishu directly. The Feishu entry service or
OpenClaw Agent must use `config/triggers.yaml` to decide whether a message
routes to S14.

## Required Behavior

1. Read `config/triggers.yaml`.
2. If the message contains any `trigger_phrases`, route to this Skill.
3. Extract only control inputs: `hotel_id`, `platform`, `period_start`,
   `period_end`, and optional display/output fields.
4. Call `S14OperationDiagnosis(config).execute(inputs)`.
5. Send `result["feishu_card"]` first. Do not send `result["feishu_message"]`
   unless the Feishu interactive-card channel is unavailable.
6. Every trigger must be a fresh run. Do not answer from previous Feishu
   messages, Agent memory, cached JSON, old `result["feishu_message"]`, or old
   report links.

## Primary Card Flow

```python
from runtime import S14OperationDiagnosis

result = S14OperationDiagnosis(config).execute(inputs)
reply = result["feishu_card"]
send_interactive(open_id, reply)
```

The card payload must use Feishu `msg_type=interactive` and a `lark_md` link:

```json
{
  "msg_type": "interactive",
  "card": {
    "elements": [
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "[点击查看诊断报告](http://47.108.200.194:8088/s14-reports/...)"
        }
      }
    ]
  }
}
```

If the sender uses Feishu OpenAPI `im/v1/messages`, convert the same card body
to the OpenAPI shape:

```json
{
  "msg_type": "interactive",
  "content": "{\"elements\":[...]}"
}
```

Do not put the report URL or the card JSON into a text message.

## Adapter Flow

```python
from runtime.feishu_adapter import (
    build_feishu_card_from_agent_output,
    build_feishu_card_reply,
    handle_feishu_text_message_card,
)

# Agent JSON -> card
agent_output = call_s14_agent(inputs)
reply = build_feishu_card_from_agent_output(agent_output)
send_interactive(open_id, reply)

# Runtime result -> card
result = S14OperationDiagnosis(config).execute(inputs)
reply = build_feishu_card_reply(result)
send_interactive(open_id, reply)

# Text trigger -> card
reply = handle_feishu_text_message_card(text)
if reply:
    send_interactive(open_id, reply)
```

## Fallback Text

`feishu_message`, `build_feishu_reply`, `build_feishu_reply_from_agent_output`,
and `handle_feishu_text_message` are legacy fallback paths. Use them only when
interactive cards are unavailable.

## Forbidden

- Do not calculate score in the entry service.
- Do not build risk level in the entry service.
- Do not create a separate Feishu reply template in the entry service.
- Do not pass `metrics`, `business_fields`, `json_payload`, or upstream Skill output.
- Do not let the Agent output natural language, Markdown, or emoji lists to Feishu.
- Do not rewrite `final_score`, `risk_text`, `report_url`, or card content.
- Do not send cached Agent text, cached JSON, previous Feishu messages, or old
  report links.
- Do not send `result["feishu_message"]` while `result["feishu_card"]` exists.
