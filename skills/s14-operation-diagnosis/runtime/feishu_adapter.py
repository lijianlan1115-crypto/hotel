"""Feishu adapter for auto-triggering S14."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from .router import should_route_to_s14
    from .reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_card,
        build_feishu_interactive_card,
        format_agent_json_output_as_card,
    )
    from .excel_reader import run_s14_from_excel
except ImportError:
    from router import should_route_to_s14
    from reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_card,
        build_feishu_interactive_card,
        format_agent_json_output_as_card,
    )
    from excel_reader import run_s14_from_excel


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER = PACKAGE_ROOT / "scripts/s14_local_report.py"
S14_DB_DSN = os.environ.get("S14_DB_DSN") or os.environ.get("HOTEL_OTA_DB_DSN")
S14_REPORT_OUTPUT_DIR = os.environ.get(
    "S14_REPORT_OUTPUT_DIR",
    "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports",
)
S14_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8088/s14-reports",
)
S14_REPORT_RETENTION_DAYS = int(os.environ.get("S14_REPORT_RETENTION_DAYS", "30"))

MODULE_LABELS = {
    "M01": "经营收益",
    "M02": "流量竞争",
    "M03": "转化断点",
    "M04": "价格房态",
    "M05": "推广ROI",
    "M06": "页面基础",
    "M07": "口碑信任",
    "M08": "执行复盘",
}


def _select_platform_from_text(text: str) -> tuple[str, str]:
    current = str(text or "")
    if "美团" in current:
        return "meituan", "美团"
    if "携程" in current:
        return "ctrip", "携程"
    if "去哪儿" in current or "去哪" in current:
        return "qunar", "去哪儿"
    if "多渠道" in current or "全渠道" in current:
        return "all", "多渠道"
    return "fliggy", "飞猪"


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _append_run_id(report_url: str, run_id: str) -> str:
    if not report_url:
        return report_url
    parts = urlsplit(str(report_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["run_id"] = run_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _replace_report_url_filename(report_url: str, filename: str) -> str:
    if not report_url:
        return report_url
    parts = urlsplit(str(report_url))
    path_parts = parts.path.rsplit("/", 1)
    new_path = f"{path_parts[0]}/{filename}" if len(path_parts) == 2 else filename
    return urlunsplit((parts.scheme, parts.netloc, new_path, "", parts.fragment))


def _cleanup_old_reports(report_dir: Path, retention_days: int = S14_REPORT_RETENTION_DAYS) -> None:
    if retention_days <= 0 or not report_dir.exists():
        return
    cutoff = datetime.now().timestamp() - retention_days * 86400
    for path in report_dir.glob("ota_diagnosis_report_*.html"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _freeze_report_file(prepared: dict[str, Any], run_id: str) -> None:
    """Snapshot current report to ota_diagnosis_report_<run_id>.html.

    This prevents new reports from overwriting old Feishu links.
    """
    report_path_text = str(prepared.get("report_file_path") or "").strip()
    if not report_path_text:
        return
    source_path = Path(report_path_text)
    if not source_path.exists() or not source_path.is_file():
        return
    report_dir = source_path.parent
    safe_run_id = "".join(ch for ch in str(run_id) if ch.isdigit()) or _new_run_id()
    unique_name = f"ota_diagnosis_report_{safe_run_id}.html"
    unique_path = report_dir / unique_name
    try:
        if source_path.resolve() != unique_path.resolve():
            unique_path.write_bytes(source_path.read_bytes())
        prepared["report_file_path"] = str(unique_path)
        if prepared.get("report_url"):
            prepared["report_url"] = _replace_report_url_filename(str(prepared["report_url"]), unique_name)
        elif S14_PUBLIC_BASE_URL:
            prepared["report_url"] = f"{S14_PUBLIC_BASE_URL.rstrip('/')}/{unique_name}"
        _cleanup_old_reports(report_dir)
    except OSError:
        return


def _prepare_current_result(result: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(result or {})
    run_id = str(prepared.get("run_id") or _new_run_id())
    prepared["run_id"] = run_id
    _freeze_report_file(prepared, run_id)
    if prepared.get("report_url"):
        prepared["report_url"] = _append_run_id(prepared["report_url"], run_id)
    prepared.pop("feishu_message", None)
    return prepared


def _risk_text(score: float) -> str:
    if score < 60:
        return "高风险"
    if score < 80:
        return "中风险"
    return "低风险"


def _platform_text(value: Any) -> str:
    mapping = {
        "fliggy": "飞猪",
        "meituan": "美团",
        "ctrip": "携程",
        "qunar": "去哪儿",
        "douyin": "抖音",
        "multi": "多渠道",
        "all": "多渠道",
    }
    return mapping.get(str(value or ""), str(value or "飞猪"))


def _fmt_num(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def _module_line(index: int, item: dict[str, Any]) -> str:
    module_id = str(item.get("module_id") or f"M{index:02d}")
    name = str(item.get("name") or MODULE_LABELS.get(module_id, "模块"))
    score = float(item.get("score") or 0)
    weight = float(item.get("weight") or 0)
    rate = int(round(score / weight * 100)) if weight else 0
    warn = " ⚠️" if rate < 60 else ""
    return f"{index} {module_id} {name:<6} {_fmt_num(score):>4}/{_fmt_num(weight, 0):<2} {rate:>3}%{warn}"


def _rich_markdown_reply(result: dict[str, Any]) -> str:
    """Legacy text fallback only. Card handlers must not call this."""
    data = _prepare_current_result(result)
    platform = _platform_text(data.get("platform") or data.get("channel_source"))
    score = float(data.get("final_score") or 0)
    risk = _risk_text(score)
    period = f"{data.get('period_start')}~{data.get('period_end')}"
    modules = data.get("module_scores") or []
    caps = data.get("caps") or []
    missing = data.get("missing_fields") or []
    report_url = str(data.get("report_url") or "")
    lines = [f"**{platform} {_fmt_num(score, 0)}/100 {risk}｜周期 {period}｜S14诊断结果**", "", "```text"]
    if modules:
        for idx, item in enumerate(modules[:8], 1):
            lines.append(_module_line(idx, item))
    else:
        lines.extend([f"综合得分 {_fmt_num(score, 0)}/100", f"风险等级 {risk}"])
    lines.append("```")
    lines.append("")
    lines.append("**诊断重点：**")
    if caps:
        for cap in caps[:4]:
            lines.append(f"- ⚠️ {cap}")
    elif missing:
        for item in missing[:4]:
            field = item.get("field", "字段") if isinstance(item, dict) else str(item)
            suggestion = item.get("suggestion", "补齐或检查字段映射") if isinstance(item, dict) else "补齐或检查字段映射"
            lines.append(f"- ⚠️ {field}：{suggestion}")
    else:
        lines.append("- 未触发强封顶，继续关注字段完整度和数据新鲜度。")
    if report_url:
        lines.append("")
        lines.append(f"📊 {report_url}")
    return "\n".join(lines)


def run_s14_local_table_mode(text: str = "") -> dict[str, Any]:
    if not S14_DB_DSN:
        raise RuntimeError("S14 database mode requires S14_DB_DSN or HOTEL_OTA_DB_DSN")
    sys.path.insert(0, str(PACKAGE_ROOT.parent))
    try:
        from runtime import S14OperationDiagnosis
    except ImportError as exc:
        raise RuntimeError(f"S14 Skill runtime not importable: {exc}") from exc
    today = date.today()
    period_start = today - timedelta(days=9)
    period_end = today
    platform, channel_source = _select_platform_from_text(text)
    diagnosis = S14OperationDiagnosis(
        {
            "db_kind": "mysql",
            "db_dsn": S14_DB_DSN,
            "report_output_dir": S14_REPORT_OUTPUT_DIR,
            "public_base_url": S14_PUBLIC_BASE_URL,
        }
    )
    return diagnosis.execute(
        {
            "hotel_id": "puyue",
            "platform": platform,
            "channel_source": channel_source,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "data_source_mode": "database",
        }
    )


def build_feishu_reply(result: dict[str, Any]) -> str:
    try:
        return _rich_markdown_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT


def build_feishu_card_reply(result: dict[str, Any]) -> dict[str, Any] | str:
    try:
        card = build_feishu_interactive_card(_prepare_current_result(result))
        assert_strict_feishu_card(card)
        return card
    except Exception:
        return FORMAT_ERROR_TEXT


def build_feishu_card_reply_json(result: dict[str, Any]) -> str:
    card = build_feishu_card_reply(result)
    if isinstance(card, str):
        return card
    return json.dumps(card, ensure_ascii=False)


def build_feishu_reply_from_agent_output(agent_output: str) -> str:
    return FORMAT_ERROR_TEXT


def build_feishu_card_from_agent_output(agent_output: str) -> str:
    return format_agent_json_output_as_card(agent_output)


def handle_feishu_text_message(text: str) -> str | None:
    if not should_route_to_s14(text):
        return None
    try:
        result = run_s14_local_table_mode(text)
        return build_feishu_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT


def handle_feishu_text_message_card(text: str) -> dict[str, Any] | str | None:
    if not should_route_to_s14(text):
        return None
    try:
        result = run_s14_local_table_mode(text)
        return build_feishu_card_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT


def handle_feishu_excel(file_path: str) -> str:
    try:
        result = run_s14_from_excel(
            file_path,
            {"report_output_dir": S14_REPORT_OUTPUT_DIR, "public_base_url": S14_PUBLIC_BASE_URL},
        )
        return build_feishu_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT


def handle_feishu_excel_card(file_path: str) -> dict[str, Any] | str:
    try:
        result = run_s14_from_excel(
            file_path,
            {"report_output_dir": S14_REPORT_OUTPUT_DIR, "public_base_url": S14_PUBLIC_BASE_URL},
        )
        return build_feishu_card_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT
