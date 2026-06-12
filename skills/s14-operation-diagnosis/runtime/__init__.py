"""OpenClaw entrypoint for S14 hotel OTA operation diagnosis."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .calculator import apply_cap_rules, calculate_all_modules
from .data_fetcher import DataFetcher
from .models import DiagnosisInput
from .reply_formatter import build_feishu_interactive_card


SKILL_ID = "s14-operation-diagnosis"
SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORT_TEMPLATE = SKILL_ROOT / "templates/ota_diagnosis_report_demo.template.html"


class S14OperationDiagnosis:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.fetcher = DataFetcher(
            db_kind=self.config.get("db_kind"),
            dsn=self.config.get("db_dsn"),
        )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        execution_steps: list[dict[str, str]] = []
        request = DiagnosisInput(**self._apply_config_defaults(inputs))
        execution_steps.append({"step": "S01_VALIDATE_INPUT", "status": "ok", "detail": "Input validated."})

        allowed_modes = {"database", "excel_upload"}
        if request.data_source_mode not in allowed_modes:
            raise ValueError(f"S14 只接受 MySQL 数据库或 Excel 上传两种数据源，拒绝模式: {request.data_source_mode}")
        if request.data_source_mode == "database" and not (self.config.get("db_kind") and self.config.get("db_dsn")):
            raise ValueError("S14 数据库模式必须配置 db_kind 和 db_dsn")
        if request.data_source_mode == "excel_upload" and not request.input_excel_path:
            raise ValueError("S14 Excel 模式必须提供 input_excel_path")

        period = {"start": str(request.period_start), "end": str(request.period_end)}
        if request.data_source_mode == "excel_upload":
            operating_data = self.fetcher.fetch_excel_data(
                excel_path=str(request.input_excel_path),
                hotel_id=request.hotel_id,
                period=period,
                platform=request.platform,
            )
            data_source = "excel_upload"
        else:
            operating_data = self.fetcher.fetch_operating_data(
                hotel_id=request.hotel_id,
                period=period,
                platform=request.platform,
            )
            data_source = "hotel_pricing_tables" if operating_data.get("source_tables") else "s14_operating_metrics"
        execution_steps.append({"step": "S02_FETCH_SOURCE", "status": "ok", "detail": f"Fetched data from {data_source}."})

        metrics = self._normalize_metrics(request, operating_data)
        module_scores = calculate_all_modules(metrics)
        final_score, caps = apply_cap_rules(module_scores, metrics)
        raw_score = round(sum(round(item.score, 1) for item in module_scores), 1)
        report_file_path, report_url = self._generate_report(request, metrics, module_scores, raw_score, final_score, caps)
        risk_level = "high" if final_score < 60 else "medium" if final_score < 80 else "low"
        run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        missing_fields = self._missing_fields(metrics)
        module_dicts = [item.__dict__ for item in module_scores]

        result = {
            "status": "partial" if caps else "ok",
            "skill_id": SKILL_ID,
            "run_id": run_id,
            "hotel_id": request.hotel_id,
            "hotel_name": request.hotel_name or metrics.get("hotel_name"),
            "platform": request.platform,
            "channel_source": request.channel_source or metrics.get("channel_source"),
            "channel_mode": request.channel_mode,
            "period_start": str(request.period_start),
            "period_end": str(request.period_end),
            "raw_score": raw_score,
            "final_score": final_score,
            "risk_level": risk_level,
            "field_completeness": metrics.get("field_completeness", 1),
            "module_scores": module_dicts,
            "caps": caps,
            "missing_fields": missing_fields,
            "formula_source": "runtime/calculator.py",
            "data_source": data_source,
            "execution_steps": execution_steps,
            "calculated_fields": self._calculated_fields(),
            "mapped_fields": self._mapped_fields(),
            "field_contract_file": "references/excel_field_mapping.csv",
            "field_mapping_source": "references/excel_field_mapping.csv",
            "approval_required": True,
            "dry_run": request.dry_run,
            "report_file_path": report_file_path,
            "report_url": report_url,
        }
        result["feishu_message"] = self._build_feishu_message(result)
        result["feishu_card"] = self._build_feishu_card(request, metrics, final_score, report_url)
        self._validate_strict_output(result)
        return result

    def _apply_config_defaults(self, inputs: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(inputs)
        if not prepared.get("output_dir") and self.config.get("report_output_dir"):
            prepared["output_dir"] = self.config["report_output_dir"]
        if not prepared.get("public_base_url") and self.config.get("public_base_url"):
            prepared["public_base_url"] = self.config["public_base_url"]
        return prepared

    def _normalize_metrics(self, request: DiagnosisInput, operating_data: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(operating_data)
        metrics.setdefault("hotel_id", request.hotel_id)
        metrics.setdefault("platform", request.platform)
        metrics.setdefault("image_quality_rating", request.image_quality_rating)
        if metrics.get("field_completeness") in (None, ""):
            metrics["field_completeness"] = self._field_completeness(metrics)
        return metrics

    def _field_completeness(self, metrics: dict[str, Any]) -> float:
        required = ["revpar", "adr", "occupancy", "available_room_nights", "exposure", "views", "payment_conversion_rate", "promo_cost", "rating_total"]
        present = sum(1 for key in required if metrics.get(key) not in (None, "", [], {}))
        return round(present / len(required), 4)

    def _missing_fields(self, metrics: dict[str, Any]) -> list[dict[str, str]]:
        fields = ["revpar", "adr", "occupancy", "available_room_nights", "exposure", "views", "payment_conversion_rate", "promo_cost", "rating_total"]
        return [
            {"field": field, "status": "missing", "suggestion": "补采或检查字段映射"}
            for field in fields
            if metrics.get(field) in (None, "", [], {})
        ]

    def _risk_text(self, score: float) -> str:
        if score < 60:
            return "高风险"
        if score < 80:
            return "中风险"
        return "低风险"

    def _platform_text(self, value: Any) -> str:
        mapping = {"fliggy": "飞猪", "meituan": "美团", "ctrip": "携程", "qunar": "去哪儿", "douyin": "抖音", "multi": "多渠道", "all": "多渠道", "multi_channel": "多渠道"}
        return mapping.get(str(value or ""), str(value or "飞猪"))

    def _fmt_num(self, value: Any, digits: int = 1) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "0"
        if number.is_integer():
            return str(int(number))
        return f"{number:.{digits}f}"

    def _module_line(self, index: int, item: dict[str, Any]) -> str:
        module_id = str(item.get("module_id") or f"M{index:02d}")
        name = str(item.get("name") or "模块")
        score = float(item.get("score") or 0)
        weight = float(item.get("weight") or 0)
        rate = int(round(score / weight * 100)) if weight else 0
        warn = " ⚠️" if rate < 60 else ""
        return f"{index} {module_id} {name:<12} {self._fmt_num(score):>4}/{self._fmt_num(weight, 0):<2} {rate:>3}%{warn}"

    def _build_feishu_message(self, result: dict[str, Any]) -> str:
        platform = self._platform_text(result.get("platform") or result.get("channel_source"))
        score = float(result.get("final_score") or 0)
        risk = self._risk_text(score)
        period = f"{result.get('period_start')}~{result.get('period_end')}"
        lines = [f"{platform} {self._fmt_num(score, 0)}/100 {risk}｜周期 {period}｜S14诊断结果", ""]
        for idx, item in enumerate((result.get("module_scores") or [])[:8], 1):
            lines.append(self._module_line(idx, item))
        lines.append("")
        lines.append("诊断重点：")
        caps = result.get("caps") or []
        missing = result.get("missing_fields") or []
        if caps:
            for cap in caps[:4]:
                lines.append(f"⚠️ {cap}")
        elif missing:
            for item in missing[:4]:
                field = item.get("field", "字段") if isinstance(item, dict) else str(item)
                suggestion = item.get("suggestion", "补齐或检查字段映射") if isinstance(item, dict) else "补齐或检查字段映射"
                lines.append(f"⚠️ {field}：{suggestion}")
        else:
            lines.append("未触发强封顶，继续关注字段完整度和数据新鲜度。")
        if missing:
            lines.extend(["", "修复内容：", "Bug", "问题", "修复"])
            for item in missing[:3]:
                if isinstance(item, dict):
                    lines.extend([str(item.get("field") or "字段"), str(item.get("status") or "missing"), str(item.get("suggestion") or "补采或检查字段映射")])
        if result.get("report_url"):
            lines.append(f"📊 {result['report_url']}")
        return "\n".join(lines)

    def _build_feishu_card(self, request: DiagnosisInput, metrics: dict[str, Any], final_score: float, report_url: str) -> dict[str, Any]:
        hotel_name = request.hotel_name or metrics.get("hotel_name") or request.hotel_id
        return build_feishu_interactive_card({"hotel_name": hotel_name, "period_start": str(request.period_start), "period_end": str(request.period_end), "final_score": final_score, "report_url": report_url})

    def _calculated_fields(self) -> list[str]:
        return [
            "hotel_id", "platform", "channel_source", "data_date", "time_grain", "period_start_field", "period_end_field",
            "revpar", "adr", "occupancy", "room_revenue", "sold_room_nights", "available_room_nights", "paid_orders", "peer_paid_orders",
            "exposure", "peer_exposure", "views", "peer_views", "booking_conversion_rate", "payment_conversion_rate", "peer_payment_conversion_rate",
            "lost_orders", "lost_amount", "price_completeness", "inventory_health_rate", "room_type_health_rate", "promo_amount", "promo_cost", "promo_roi",
            "promo_orders", "promo_clicks", "promo_exposure", "promo_ctr", "promo_cpc", "image_quality_rating", "video_status", "room_selling_point_status",
            "entry_tag_quality", "rating_total", "bad_review_rate", "unreplied_reviews", "completed_actions", "pending_actions", "review_reason", "field_completeness",
        ]

    def _mapped_fields(self) -> list[dict[str, str]]:
        return [{"field": field, "role": "formula/control", "source": "database/excel", "formula_module": "S14_V4"} for field in self._calculated_fields()]

    def _validate_strict_output(self, result: dict[str, Any]) -> None:
        expected_modules = ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08"]
        actual_modules = [item["module_id"] for item in result["module_scores"]]
        if actual_modules != expected_modules:
            raise ValueError(f"S14 module calculation order is invalid: {actual_modules}")
        total_weight = round(sum(float(item["weight"]) for item in result["module_scores"]), 2)
        if total_weight != 100:
            raise ValueError(f"S14 module weights must sum to 100, got {total_weight}")
        if not result.get("feishu_message") or "S14诊断结果" not in result["feishu_message"]:
            raise ValueError("S14 feishu_message format is missing or invalid")
        if not result.get("report_url"):
            raise ValueError("S14 report_url is required")

    def _generate_report(self, request: DiagnosisInput, metrics: dict[str, Any], module_scores: list[Any], raw_score: float, final_score: float, caps: list[str]) -> tuple[str, str]:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = "ota_diagnosis_report.html"
        report_path = output_dir / filename
        style = self._load_report_style()
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        risk_text = self._risk_text(final_score)
        cap_html = "".join(f"<li>{self._esc(cap)}</li>" for cap in caps) or "<li>本次未触发强封顶，继续关注数据新鲜度和字段完整度。</li>"
        module_rows = [["模块", "得分", "得分率", "状态", "核心依据"]]
        for item in module_scores:
            rate = item.score / item.weight if item.weight else 0
            module_rows.append([
                f"{item.module_id} {self._esc(item.name)}",
                f"<div class='score-bar'><span>{item.score:.1f} / {item.weight:.0f}</span><div class='bar-track'><div class='bar-fill {self._status_class(rate)}' style='width:{rate*100:.0f}%'></div></div><b>{rate*100:.0f}%</b></div>",
                f"{rate*100:.0f}%",
                f"<span class='status {self._status_class(rate)}'>{self._status_label(rate)}</span>",
                "<br>".join(self._esc(reason) for reason in item.reasons),
            ])
        metric_rows = [["指标", "当前值", "口径", "判断"], ["RevPAR", self._money(metrics.get("revpar")), "revpar", "收益锚点"], ["ADR", self._money(metrics.get("adr")), "adr", "价格水平"], ["出租率", self._pct(metrics.get("occupancy")), "occupancy", "经营效率"], ["曝光", self._num_text(metrics.get("exposure")), "exposure", "流量入口"], ["浏览", self._num_text(metrics.get("views")), "views", "详情页访问"], ["支付转化率", self._pct(metrics.get("payment_conversion_rate")), "payment_conversion_rate", "转化结果"]]
        missing_rows = [["缺失字段", "当前状态", "处理建议", "责任来源"]]
        for item in self._missing_fields(metrics):
            missing_rows.append([self._esc(item["field"]), self._esc(item["status"]), self._esc(item["suggestion"]), "S14 数据映射"])
        html_text = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>酒店 OTA 全面诊断报告</title><style>{style}</style></head><body>
<header class='app-header'><div class='header-inner'><div class='title-block'><h1>酒店 OTA 全面诊断报告</h1><p>{self._esc(request.hotel_name or metrics.get('hotel_name') or request.hotel_id)}｜{self._esc(request.channel_source or metrics.get('channel_source') or request.platform)}｜周期：{request.period_start} 至 {request.period_end}｜生成时间：{generated_at}</p></div></div></header>
<div class='layout'><main>
<section id='overview'><div class='section-head'><div><h2>顶部总览卡片</h2><p>本报告由 S14 OpenClaw 独立 Skill 生成。</p></div><span class='status {self._status_class(final_score/100)}'>风险：{risk_text}</span></div><div class='section-body'><div class='kpi-grid'><div class='kpi'><label>总分</label><strong class='num'>{final_score:.0f} / 100</strong><span>原始分 {raw_score:.1f}</span></div><div class='kpi'><label>数据可信度</label><strong class='num'>{float(metrics.get('field_completeness', 0))*100:.0f}%</strong><span>缺失字段进入补采提示</span></div></div><div class='cap-alert'><b>封顶/校准规则</b><span><ul>{cap_html}</ul></span></div></div></section>
<section id='modules'><div class='section-head'><div><h2>模块得分条形图</h2></div></div><div class='section-body'>{self._render_table(module_rows)}</div></section>
<section id='metrics'><div class='section-head'><div><h2>经营指标表</h2></div></div><div class='section-body'>{self._render_table(metric_rows)}</div></section>
<section id='missing'><div class='section-head'><div><h2>补采提示</h2></div></div><div class='section-body'>{self._render_table(missing_rows)}</div></section>
</main></div></body></html>"""
        report_path.write_text(html_text, encoding="utf-8")
        if request.public_base_url:
            return str(report_path), f"{request.public_base_url.rstrip('/')}/{report_path.name}?run_id={ts}"
        return str(report_path), report_path.resolve().as_uri()

    def _load_report_style(self) -> str:
        if REPORT_TEMPLATE.exists():
            template = REPORT_TEMPLATE.read_text(encoding="utf-8")
            match = re.search(r"<style>(.*?)</style>", template, re.S)
            if match:
                return match.group(1)
        return "body{font-family:Arial,'Microsoft YaHei',sans-serif;background:#f6f7f9;color:#1d2430}.section,section{background:#fff;padding:18px;margin:16px;border:1px solid #ddd}.data-table{width:100%;border-collapse:collapse}.data-table th,.data-table td{border:1px solid #ddd;padding:8px}"

    def _render_table(self, rows: list[list[Any]]) -> str:
        if not rows:
            return ""
        head = "".join(f"<th>{self._esc(value)}</th>" for value in rows[0])
        body = []
        for row in rows[1:]:
            body.append("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>")
        return f"<table class='data-table'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def _esc(self, value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def _num_text(self, value: Any) -> str:
        if value in (None, ""):
            return "未获取"
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return self._esc(value)

    def _money(self, value: Any) -> str:
        return self._num_text(value)

    def _pct(self, value: Any) -> str:
        if value in (None, ""):
            return "未获取"
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return self._esc(value)

    def _status_class(self, rate: float) -> str:
        if rate < 0.6:
            return "bad"
        if rate < 0.8:
            return "warn"
        return "good"

    def _status_label(self, rate: float) -> str:
        if rate < 0.6:
            return "严重短板"
        if rate < 0.8:
            return "需要优化"
        return "正常/轻微可优化"
