# Testing S14 OpenClaw Skill

Run from this folder:

```bash
python3 -B tests/smoke_test.py
python3 -B tests/excel_smoke_test.py
```

Expected output:

```text
S14 smoke test passed
final_score=...
module_count=8
report_file_path=...
```

What this verifies:

- `config/database_schema.sql` can create the required S14 database table.
- The runtime reads diagnosis facts from SQLite through `runtime/data_fetcher.py`.
- `runtime/calculator.py` calculates all 8 module scores.
- The runtime returns an HTML report path.

The smoke test uses a temporary database and temporary report output directory.
It does not modify production data.

`excel_smoke_test.py` additionally verifies Chinese Excel headers are mapped
through `references/excel_field_mapping.csv` before scoring.
