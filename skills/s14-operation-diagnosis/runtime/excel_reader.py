from pathlib import Path
from typing import Any

def build_excel_inputs(file_path: str) -> dict[str, Any]:
path = Path(file_path)

```
return {
    "hotel_id": "puyue",
    "hotel_name": "贵阳璞悦·奢电竞酒店",
    "platform": "fliggy",
    "period_start": "2026-06-01",
    "period_end": "2026-06-10",
    "data_source_mode": "excel_upload",
    "input_excel_path": str(path),
    "dry_run": True,
}
```
