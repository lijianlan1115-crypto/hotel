# S14 OpenClaw Deployment

This folder is self-contained and can be copied as one OpenClaw Skill package:

```text
s14-operation-diagnosis/
├── SKILL.md
├── openclaw.skill.yaml
├── config/
│   ├── fields.yaml
│   ├── triggers.yaml
│   └── database_schema.sql
├── templates/
│   └── ota_diagnosis_report_demo.template.html
├── references/
│   ├── input_schema.json
│   ├── output_schema.json
│   ├── feishu_routing.md
│   ├── excel_field_mapping.csv
│   ├── excel_field_mapping.xlsx
│   ├── rules.md
│   ├── runtime_commands.md
│   └── examples.md
└── runtime/
    ├── __init__.py
    ├── models.py
    ├── calculator.py
    ├── data_fetcher.py
    └── router.py
```

## Copy Scope

Copy the whole `s14-operation-diagnosis/` directory. Do not copy only
`runtime/`, because OpenClaw also needs the schema, field config, deployment
manifest, and HTML report template.

Exclude:

- `__pycache__/`
- `.DS_Store`
- local demo outputs

## OpenClaw Config

Database mode config:

```json
{
  "db_kind": "sqlite",
  "db_dsn": "/path/to/hotel_ota.sqlite",
  "report_output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports"
}
```

MySQL config:

```json
{
  "db_kind": "mysql",
  "db_dsn": "mysql://user:password@host:3306/hotel_ota",
  "report_output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports"
}
```

Excel upload mode still needs report output config, but does not need `db_dsn`:

```json
{
  "report_output_dir": "/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports",
  "public_base_url": "http://47.108.200.194:8088/s14-reports"
}
```

## Report URL Service

Do not start a new HTTP port from the Skill. Keep one static web service running
with Nginx or systemd. The Skill writes:

```text
/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports/ota_diagnosis_report_demo.html
```

and returns:

```text
http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html
```

For quick testing, `s14-report-web.service` or Nginx can serve the `public/`
directory permanently. The Skill only regenerates the HTML when called.

## Runtime Contract

OpenClaw should call:

```python
S14OperationDiagnosis(config).execute(inputs)
```

Inputs must validate against `references/input_schema.json`.

S14 accepts only two controlled data sources: `database` and `excel_upload`.
OpenClaw must not pass `metrics`, `business_fields`, `json_payload`,
`manual_diagnosis_input`, or any upstream Skill output.

## Feishu Routing

Trigger words and reply policy live in:

```text
config/triggers.yaml
```

The Feishu entry service or OpenClaw Agent should read that file and route
matching messages to this Skill. After execution it must call
`runtime/feishu_adapter.py::build_feishu_reply(result)` and send that returned
text. Do not send cached Agent text or an old `result["feishu_message"]`
directly.

## Database Contract

Configure `db_dsn` to the production database `hotel_pricing`.
The runtime reads these business tables directly:

- `jd01_bookings`
- `jd04_extensions`
- `fact_daily_metrics`
- `fact_monthly_metrics`
- `fact_room_fee_daily`
- `fact_room_status_snapshot`

Column aliases and table responsibilities are documented in
`config/hotel_pricing_sources.yaml`. Other jobs may collect or sync data into
these tables, but S14 must query the tables itself.

## HTML Report Template

The final report uses `templates/ota_diagnosis_report_demo.template.html` as the
visual style source. The runtime extracts the template CSS and writes
`ota_diagnosis_report_demo.html` into the configured output directory on every
run, so old simplified reports are overwritten.
