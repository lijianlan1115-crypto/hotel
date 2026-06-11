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


def detect_channels_from_excel(file_path: str, max_rows: int = 30) -> list[str]:
    """
    从 Excel 的 sheet 名、表头、前 max_rows 行内容中自动识别 OTA 渠道。
    识别到哪些渠道，报告就展示哪些渠道。
    """
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
        for keyword in keywords:
            if keyword.lower() in full_text:
                detected.append(channel)
                break

    return detected


def build_channel_summary(channels: list[str]) -> dict[str, Any]:
    """
    给报告顶部和后续渲染使用。
    """
    if not channels:
        return {
            "channel_mode": "unknown",
            "channel_title": "未识别",
            "channel_count": 0,
            "channel_labels": [],
        }

    labels = [CHANNEL_LABELS.get(channel, channel) for channel in channels]

    return {
        "channel_mode": "single" if len(channels) == 1 else "multi",
        "channel_title": " / ".join(labels),
        "channel_count": len(channels),
        "channel_labels": labels,
    }


def build_excel_inputs(file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    channels = detect_channels_from_excel(str(path))
    channel_summary = build_channel_summary(channels)

    return {
        "hotel_id": "puyue",
        "hotel_name": "贵阳璞悦·奢电竞酒店",

        # 兼容旧字段：以前只有 platform
        "platform": "multi" if len(channels) != 1 else channels[0],

        # 新字段：多渠道结构
        "platforms": channels,
        "channels": channels,

        "channel_source": channel_summary["channel_title"],
        "channel_mode": channel_summary["channel_mode"],
        "channel_count": channel_summary["channel_count"],
        "channel_labels": channel_summary["channel_labels"],
        "channel_summary": channel_summary,

        "period_start": "2026-06-01",
        "period_end": "2026-06-10",
        "data_source_mode": "excel_upload",
        "input_excel_path": str(path),
        "dry_run": True,
    }


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
    return S14OperationDiagnosis(runtime_config).execute(inputs)
