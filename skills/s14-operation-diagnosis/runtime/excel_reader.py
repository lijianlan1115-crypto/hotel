from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


CHANNEL_LABELS = {
    "fliggy": "飞猪",
    "meituan": "美团",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
}

CHANNEL_KEYWORDS = {
    "fliggy": ["飞猪", "fliggy", "淘系", "阿里旅行"],
    "meituan": ["美团", "大众点评", "meituan"],
    "ctrip": ["携程", "ctrip", "trip.com", "trip"],
    "qunar": ["去哪儿", "qunar"],
    "tongcheng": ["同程", "艺龙", "tongcheng", "elong"],
}


DETECTED_META_KEYS = [
    "detected_channels",
    "detected_channel_labels",
    "detected_channel_count",
    "detected_channel_title",
]


def detect_channels_from_excel(file_path: str, max_rows: int = 30) -> list[str]:
    path = Path(file_path).expanduser().resolve()

    if load_workbook is None:
        return []

    workbook = load_workbook(path, read_only=True, data_only=True)
    text_pool: list[str] = []

    try:
        for sheet_name in workbook.sheetnames:
            text_pool.append(str(sheet_name))

            ws = workbook[sheet_name]
            for row in ws.iter_rows(max_row=max_rows, values_only=True):
                for cell in row:
                    if cell is not None:
                        text_pool.append(str(cell))
    finally:
        workbook.close()

    full_text = " ".join(text_pool).lower()
    detected: list[str] = []

    for channel, keywords in CHANNEL_KEYWORDS.items():
        if any(keyword.lower() in full_text for keyword in keywords):
            detected.append(channel)

    return detected


def build_channel_summary(channels: list[str]) -> dict[str, Any]:
    labels = [CHANNEL_LABELS.get(channel, channel) for channel in channels]

    return {
        "detected_channels": channels,
        "detected_channel_labels": labels,
        "detected_channel_count": len(channels),
        "detected_channel_title": " / ".join(labels) if labels else "",
    }


def build_excel_inputs(file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    detected_channels = detect_channels_from_excel(str(path))
    detected_channel_summary = build_channel_summary(detected_channels)

    inputs = {
        "hotel_id": "puyue",
        "hotel_name": "贵阳璞悦·奢电竞酒店",

        # 原有字段保持不变，避免影响之前功能
        "platform": "multi",
        "channel_source": "多渠道",
        "channel_mode": "multi",

        "period_start": "2026-06-01",
        "period_end": "2026-06-10",
        "data_source_mode": "excel_upload",
        "input_excel_path": str(path),
        "dry_run": True,
    }

    # 只新增展示辅助字段，不覆盖原有字段
    inputs.update(detected_channel_summary)

    return inputs


def run_s14_from_excel(
    file_path: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from . import S14OperationDiagnosis
    except ImportError:
        from runtime import S14OperationDiagnosis

    runtime_config = config or {}
    inputs = build_excel_inputs(file_path)

    diagnosis_inputs = dict(inputs)

    # 新增字段不传给 DiagnosisInput，避免 unexpected field
    detected_meta = {
        key: diagnosis_inputs.pop(key)
        for key in DETECTED_META_KEYS
        if key in diagnosis_inputs
    }

    result = S14OperationDiagnosis(runtime_config).execute(diagnosis_inputs)

    # 诊断结果如果是 dict，再把识别到的渠道信息补回去给页面/飞书使用
    if isinstance(result, dict):
        result.update(detected_meta)

    return result
