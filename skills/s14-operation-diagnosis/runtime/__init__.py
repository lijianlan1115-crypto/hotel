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
        """Execute S14 diagnosis with strict input/output fields."""
        execution_steps: list[dict[str, str]] = []

        request = DiagnosisInput(**self._apply_config_defaults(inputs))
        execution_steps.append({
            "step": "S01_VALIDATE_INPUT",
            "status": "ok",
            "detail": "Input validated by runtime/models.py and references/input_schema.json contract.",
        })

        # 严格数据源校验：只接受 MySQL 和 Excel 两种模式，拒绝其他数据源
        allowed_modes = {"database", "excel_upload"}
        if request.data_source_mode not in allowed_modes:
            raise ValueError(
                f"S14 只接受 MySQL 数据库或 Excel 上传两种数据源，"
                f"拒绝模式: {request.data_source_mode}。"
                f"请通过 db_dsn 或 input_excel_path 提供数据。"
            )
        if request.data_source_mode == "database" and not (self.config.get("db_kind") and self.config.get("db_dsn")):
            raise ValueError("S14 数据库模式必须配置 db_kind 和 db_dsn")
        if request.data_source_mode == "excel_upload" and not request.input_excel_path:
            raise ValueError("S14 Excel 模式必须提供 input_excel_path")
        execution_steps.append({
            "step": "S01B_VALIDATE_DATA_SOURCE",
            "status": "ok",
            "detail": f"Data source mode '{request.data_source_mode}' validated. Only MySQL/Excel are accepted.",
        })

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
        execution_steps.append({
            "step": "S02_FETCH_SOURCE",
            "status": "ok",
            "detail": f"Fetched and aggregated period facts from {data_source} via runtime/data_fetcher.py.",
        })

        metrics = self._normalize_metrics(request, operating_data)
        execution_steps.append({
            "step": "S03_NORMALIZE_FIELDS",
            "status": "ok",
            "detail": "Normalized control fields, defaults, and field_completeness in runtime/__init__.py.",
        })

        module_scores = calculate_all_modules(metrics)
        execution_steps.append({
            "step": "S04_CALCULATE_MODULES",
            "status": "ok",
            "detail": "Calculated M01-M08 in fixed order using runtime/calculator.py.",
        })

        final_score, caps = apply_cap_rules(module_scores, metrics)
        raw_score = round(sum(round(item.score, 1) for item in module_scores), 1)
        execution_steps.append({
            "step": "S05_APPLY_CAP_RULES",
            "status": "ok",
            "detail": "Applied total-score cap rules using runtime/calculator.py::apply_cap_rules.",
        })

        report_file_path, report_url = self._generate_report(request, metrics, module_scores, raw_score, final_score, caps)
        execution_steps.append({
            "step": "S06_RENDER_REPORT",
            "status": "ok",
            "detail": "Rendered HTML report with templates/ota_diagnosis_report_demo.template.html.",
        })
        risk_level = "high" if final_score < 60 else "medium" if final_score < 80 else "low"
        feishu_message = self._build_feishu_message(request, metrics, final_score, risk_level, report_url, data_source)
        calculated_fields = self._calculated_fields()
        mapped_fields = self._mapped_fields()

        result = {
            "status": "partial" if caps else "ok",
            "skill_id": SKILL_ID,
            "run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
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
            "module_scores": [item.__dict__ for item in module_scores],
            "caps": caps,
            "missing_fields": self._missing_fields(metrics),
            "formula_source": "runtime/calculator.py",
            "data_source": data_source,
            "execution_steps": execution_steps,
            "calculated_fields": calculated_fields,
            "mapped_fields": mapped_fields,
            "field_contract_file": "references/excel_field_mapping.xlsx",
            "field_mapping_source": "config/excel_field_mapping.yaml",
            "feishu_message": feishu_message,
            "approval_required": True,
            "dry_run": request.dry_run,
            "report_file_path": report_file_path,
            "report_url": report_url,
        }
        self._validate_strict_output(result)
        execution_steps.append({
            "step": "S07_VALIDATE_OUTPUT",
            "status": "ok",
            "detail": "Validated fixed output format, module coverage, score weights, Feishu message, and report URL.",
        })
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
        required = [
            "revpar",
            "adr",
            "occupancy",
            "available_room_nights",
            "exposure",
            "views",
            "payment_conversion_rate",
            "promo_cost",
            "rating_total",
        ]
        present = sum(1 for key in required if metrics.get(key) not in (None, "", [], {}))
        return round(present / len(required), 4)

    def _missing_fields(self, metrics: dict[str, Any]) -> list[dict[str, str]]:
        fields = ["revpar", "adr", "occupancy", "available_room_nights", "exposure", "views", "payment_conversion_rate", "promo_cost", "rating_total"]
        return [
            {"field": field, "status": "missing", "suggestion": "补采或检查字段映射"}
            for field in fields
            if metrics.get(field) in (None, "", [], {})
        ]

    def _build_feishu_message(self, request: DiagnosisInput, metrics: dict[str, Any], final_score: float, risk_level: str, report_url: str, data_source: str) -> str:
        risk_text = {"high": "高风险", "medium": "中风险", "low": "低风险"}[risk_level]
        hotel_name = request.hotel_name or metrics.get("hotel_name") or request.hotel_id
        return f"""【S14 酒店 OTA 诊断报告已生成】

酒店：{hotel_name}
周期：{request.period_start} 至 {request.period_end}
综合得分：{final_score:.0f} / 100
风险等级：{risk_text}

报告链接：
🔗点击查看报告： {report_url}
"""

    def _calculated_fields(self) -> list[str]:
        return [
            "hotel_id",
            "platform",
            "channel_source",
            "data_date",
            "time_grain",
            "period_start_field",
            "period_end_field",
            "revpar",
            "adr",
            "occupancy",
            "room_revenue",
            "sold_room_nights",
            "available_room_nights",
            "exposure",
            "views",
            "peer_rank",
            "booking_conversion_rate",
            "payment_conversion_rate",
            "lost_orders",
            "lost_amount",
            "price_completeness",
            "inventory_health_rate",
            "room_type_health_rate",
            "promo_amount",
            "promo_cost",
            "promo_roi",
            "image_quality_rating",
            "video_status",
            "room_selling_point_status",
            "entry_tag_quality",
            "rating_total",
            "bad_review_rate",
            "unreplied_reviews",
            "completed_actions",
            "pending_actions",
            "review_reason",
            "field_completeness",
        ]

    def _mapped_fields(self) -> list[dict[str, str]]:
        return [
            {"field": "hotel_id", "role": "control", "source": "input/database/excel", "formula_module": "filter"},
            {"field": "platform", "role": "control", "source": "input/database/excel", "formula_module": "channel_filter"},
            {"field": "channel_source", "role": "control", "source": "database/excel", "formula_module": "channel_display"},
            {"field": "data_date", "role": "time", "source": "database/excel", "formula_module": "period_filter"},
            {"field": "time_grain", "role": "time", "source": "database/excel", "formula_module": "aggregation_context"},
            {"field": "period_start_field", "role": "time", "source": "excel", "formula_module": "period_overlap_filter"},
            {"field": "period_end_field", "role": "time", "source": "excel", "formula_module": "period_overlap_filter"},
            {"field": "revpar", "role": "formula", "source": "database/excel", "formula_module": "M01"},
            {"field": "adr", "role": "formula", "source": "database/excel", "formula_module": "M01"},
            {"field": "occupancy", "role": "formula", "source": "database/excel", "formula_module": "M01"},
            {"field": "room_revenue", "role": "evidence", "source": "database/excel", "formula_module": "M01"},
            {"field": "sold_room_nights", "role": "evidence", "source": "database/excel", "formula_module": "M01"},
            {"field": "available_room_nights", "role": "formula", "source": "database/excel", "formula_module": "M01/C01"},
            {"field": "exposure", "role": "formula", "source": "database/excel", "formula_module": "M02/C03"},
            {"field": "views", "role": "formula", "source": "database/excel", "formula_module": "M02/C03"},
            {"field": "peer_rank", "role": "formula", "source": "database/excel", "formula_module": "M02"},
            {"field": "booking_conversion_rate", "role": "formula", "source": "database/excel", "formula_module": "M03"},
            {"field": "payment_conversion_rate", "role": "formula", "source": "database/excel", "formula_module": "M03"},
            {"field": "lost_orders", "role": "formula", "source": "database/excel", "formula_module": "M03"},
            {"field": "lost_amount", "role": "evidence", "source": "database/excel", "formula_module": "M03"},
            {"field": "price_completeness", "role": "formula", "source": "database/excel", "formula_module": "M04"},
            {"field": "inventory_health_rate", "role": "formula", "source": "database/excel", "formula_module": "M04"},
            {"field": "room_type_health_rate", "role": "formula", "source": "database/excel", "formula_module": "M04"},
            {"field": "promo_amount", "role": "formula", "source": "database/excel", "formula_module": "M05"},
            {"field": "promo_cost", "role": "formula", "source": "database/excel", "formula_module": "M05/C05"},
            {"field": "promo_roi", "role": "formula", "source": "database/excel", "formula_module": "M05"},
            {"field": "promo_detail_ready", "role": "cap_rule", "source": "database/excel", "formula_module": "C05"},
            {"field": "image_quality_rating", "role": "formula", "source": "database/excel/input_default", "formula_module": "M06"},
            {"field": "video_status", "role": "formula", "source": "database/excel", "formula_module": "M06"},
            {"field": "room_selling_point_status", "role": "formula", "source": "database/excel", "formula_module": "M06"},
            {"field": "entry_tag_quality", "role": "formula", "source": "database/excel", "formula_module": "M06"},
            {"field": "rating_total", "role": "formula", "source": "database/excel", "formula_module": "M07"},
            {"field": "bad_review_rate", "role": "formula", "source": "database/excel", "formula_module": "M07"},
            {"field": "unreplied_reviews", "role": "formula", "source": "database/excel", "formula_module": "M07"},
            {"field": "completed_actions", "role": "formula", "source": "database/excel", "formula_module": "M08"},
            {"field": "pending_actions", "role": "formula", "source": "database/excel", "formula_module": "M08"},
            {"field": "review_reason", "role": "formula", "source": "database/excel", "formula_module": "M08"},
            {"field": "field_completeness", "role": "formula", "source": "database/excel/runtime", "formula_module": "M08/C07"},
        ]

    def _validate_strict_output(self, result: dict[str, Any]) -> None:
        expected_modules = ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08"]
        actual_modules = [item["module_id"] for item in result["module_scores"]]
        if actual_modules != expected_modules:
            raise ValueError(f"S14 module calculation order is invalid: {actual_modules}")

        total_weight = round(sum(float(item["weight"]) for item in result["module_scores"]), 2)
        if total_weight != 100:
            raise ValueError(f"S14 module weights must sum to 100, got {total_weight}")

        if result["formula_source"] != "runtime/calculator.py":
            raise ValueError("S14 formula_source must be runtime/calculator.py")
        if result["data_source"] not in {"hotel_pricing_tables", "s14_operating_metrics", "excel_upload"}:
            raise ValueError("S14 data_source must be hotel_pricing_tables, s14_operating_metrics, or excel_upload")
        if result.get("field_contract_file") != "references/excel_field_mapping.xlsx":
            raise ValueError("S14 field_contract_file must point to references/excel_field_mapping.xlsx")
        if len(result.get("mapped_fields", [])) < len(result.get("calculated_fields", [])):
            raise ValueError("S14 mapped_fields must cover all calculated/control fields")
        if not result.get("feishu_message") or "【S14 酒店 OTA 诊断报告已生成】" not in result["feishu_message"]:
            raise ValueError("S14 feishu_message format is missing or invalid")
        if not result.get("report_url"):
            raise ValueError("S14 report_url is required")
        if result.get("dry_run") is not True or result.get("approval_required") is not True:
            raise ValueError("S14 must remain dry_run with approval_required=true")

    def _generate_report(self, request: DiagnosisInput, metrics: dict[str, Any], module_scores: list[Any], raw_score: float, final_score: float, caps: list[str]) -> tuple[str, str]:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename with timestamp to avoid caching issues
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = "ota_diagnosis_report.html"
        report_path = output_dir / filename

        style = self._load_report_style()
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        risk = "high" if final_score < 60 else "medium" if final_score < 80 else "low"
        risk_text = {"high": "高风险", "medium": "中风险", "low": "低风险"}[risk]
        data_source_label = "hotel_pricing 业务表" if metrics.get("source_tables") else "Excel上传" if metrics.get("data_source_mode") == "excel_upload" else "s14_operating_metrics 兼容表"
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

        metric_rows = [["指标", "当前值", "口径", "判断"]]
        metric_rows += [
            ["RevPAR", self._money(metrics.get("revpar")), "标准字段 revpar", "收益锚点"],
            ["ADR", self._money(metrics.get("adr")), "标准字段 adr", "价格水平"],
            ["出租率", self._pct(metrics.get("occupancy")), "标准字段 occupancy", "经营效率"],
            ["曝光", self._num_text(metrics.get("exposure")), "标准字段 exposure", "流量入口"],
            ["浏览", self._num_text(metrics.get("views")), "标准字段 views", "详情页访问"],
            ["支付转化率", self._pct(metrics.get("payment_conversion_rate")), "标准字段 payment_conversion_rate", "转化结果"],
        ]

        promo_rows = [["指标", "值", "口径", "判断"]]
        promo_rows += [
            ["推广订单金额", self._money(metrics.get("promo_amount")), "标准字段 promo_amount", "推广产出"],
            ["推广花费", self._money(metrics.get("promo_cost")), "标准字段 promo_cost", "推广成本"],
            ["ROI", self._num_text(metrics.get("promo_roi")), "订单金额/推广花费", "推广效率"],
            ["推广明细", "已补齐" if metrics.get("promo_detail_ready") else "未补齐", "曝光/点击/CPC/成交明细", "影响封顶规则"],
        ]

        page_rows = [["项目", "状态", "来源", "判断"]]
        page_rows += [
            ["图片质量", self._esc(metrics.get("image_quality_rating", "unknown")), "数据库/人工表单镜像", "页面基础"],
            ["视频状态", self._esc(metrics.get("video_status", "unknown")), "数据库/人工表单镜像", "内容完整度"],
            ["房型卖点", self._esc(metrics.get("room_selling_point_status", "unknown")), "数据库/人工表单镜像", "转化支撑"],
            ["入口标签", self._esc(metrics.get("entry_tag_quality", "unknown")), "数据库/人工表单镜像", "搜索和入口质量"],
        ]

        reputation_rows = [["指标", "值", "口径", "判断"]]
        reputation_rows += [
            ["平台评分", self._num_text(metrics.get("rating_total")), "标准字段 rating_total", "信任锚点"],
            ["差评率", self._pct(metrics.get("bad_review_rate")), "标准字段 bad_review_rate", "口碑风险"],
            ["未回复评价", self._num_text(metrics.get("unreplied_reviews")), "标准字段 unreplied_reviews", "服务响应"],
        ]

        missing_rows = [["缺失字段", "当前状态", "处理建议", "责任来源"]]
        for item in self._missing_fields(metrics):
            missing_rows.append([self._esc(item["field"]), self._esc(item["status"]), self._esc(item["suggestion"]), "S14 数据库映射"])

        task_rows = [["优先级", "负责人", "整改动作", "复盘指标", "周期"]]
        task_rows += [
            ["P0", self._esc(request.owner_user_id or "OTA运营"), "补齐 S14 数据库关键经营字段，确保报告不是基于缺失口径判断", "字段完整度、数据新鲜度", "3天"],
            ["P1", "收益经理", "复盘 RevPAR、ADR、出租率和核心房型库存健康度", "RevPAR、ADR、出租率", "7天"],
            ["P1", "运营负责人", "检查曝光、浏览、支付转化和推广 ROI 的断点", "曝光、浏览、支付转化率、ROI", "7天"],
            ["P2", "门店店长", "完善图片、视频、房型卖点和入口标签", "页面质量、转化率", "14天"],
        ]
"

        html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>酒店 OTA 全面诊断报告</title>
  <style>{style}</style>
</head>
<body>
  <header class="app-header"><div class="header-inner"><div class="title-block">
    <h1>酒店 OTA 全面诊断报告</h1>
    <p>{self._esc(request.hotel_name or metrics.get("hotel_name") or request.hotel_id)}｜{self._esc(request.channel_source or metrics.get("channel_source") or request.platform)}｜周期：{request.period_start} 至 {request.period_end}｜生成时间：{generated_at}</p>
  </div><div class="actions"><button class="btn primary" onclick="window.print()">导出报告</button></div></div></header>
  <div class="layout">
    <nav class="sidebar dashboard-only">
      <a href="#overview">顶部总览卡片</a><a href="#modules">模块得分条形图</a><a href="#metrics">经营指标表</a><a href="#promotion">推广效率表</a><a href="#page">页面基础表</a><a href="#reputation">口碑分析表</a><a href="#tasks">整改任务表</a><a href="#missing">补采提示</a>
    </nav>
    <main>
      <section id="overview"><div class="section-head"><div><h2>顶部总览卡片</h2><p>{self._esc(report_note)}</p></div><span class="status {self._status_class(final_score/100)}">风险：{risk_text}</span></div>
        <div class="section-body"><div class="kpi-grid">
          <div class="kpi"><label>总分</label><strong class="num">{final_score:.0f} / 100</strong><span>原始分 {raw_score:.1f}</span></div>
          <div class="kpi"><label>数据可信度</label><strong class="num">{float(metrics.get("field_completeness", 0))*100:.0f}%</strong><span>缺失字段进入补采提示</span></div>
          <div class="kpi"><label>诊断渠道</label><strong>{self._esc(request.channel_source or metrics.get("channel_source") or request.platform)}</strong><span>platform={self._esc(request.platform)}</span></div>
          <div class="kpi"><label>数据来源</label><strong>{self._esc(data_source_label)}</strong><span>{self._esc(', '.join(metrics.get("source_tables", [])) if metrics.get("source_tables") else metrics.get("data_source_mode", "database"))}</span></div>
        </div><div class="cap-alert"><b>封顶/校准规则</b><span><ul>{cap_html}</ul></span><span class="status warn">按 S14 规则</span></div></div>
      </section>
      <section id="modules"><div class="section-head"><div><h2>模块得分条形图</h2><p>8个模块得分 / 权重 / 得分率，低于60%标红，60-79%标黄</p></div></div><div class="section-body">{self._render_table(module_rows)}</div></section>
      <section id="metrics"><div class="section-head"><div><h2>经营指标表</h2></div></div><div class="section-body">{self._render_table(metric_rows)}</div></section>
      <section id="promotion"><div class="section-head"><div><h2>推广效率表</h2><p>推广金额、花费、ROI 和明细完整度</p></div></div><div class="section-body">{self._render_table(promo_rows)}</div></section>
      <section id="page"><div class="section-head"><div><h2>页面展示与入口基础</h2><p>图片、视频、卖点、入口标签</p></div></div><div class="section-body">{self._render_table(page_rows)}</div></section>
      <section id="reputation"><div class="section-head"><div><h2>口碑分析</h2><p>平台评分、差评率和未回复评价</p></div></div><div class="section-body">{self._render_table(reputation_rows)}</div></section>
      <section id="tasks"><div class="section-head"><div><h2>整改任务表</h2><p>动作、负责人、截止时间、复盘指标，P0/P1/P2优先级</p></div></div><div class="section-body">{self._render_table(task_rows)}</div></section>
      <section id="missing"><div class="section-head"><div><h2>补采提示</h2><p>缺失字段、影响、采集方式；数据缺失不等于经营差，但影响可信度</p></div></div><div class="section-body">{self._render_table(missing_rows)}</div></section>
    </main>
  </div>
</body>
</html>"""
        report_path.write_text(html_text, encoding="utf-8")
        if request.public_base_url:
            # Add timestamp query parameter to force cache refresh
            report_url = f"{request.public_base_url.rstrip('/')}/{report_path.name}?t={ts}"
            return str(report_path), report_url
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
        if value in (None, ""):
            return "未获取"
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return self._esc(value)

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
