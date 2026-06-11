#!/usr/bin/env python3
"""S14 standalone report generator with built-in demo data.
Generates ota_diagnosis_report_demo.html without requiring xlsx files.
"""
from __future__ import annotations
import csv
import html
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path("/opt/openclaw/workspaces/s14-feishu-test")
MANUAL_FORM = WORKSPACE / "skills/s14-operation-diagnosis/inputs/s14_manual_form_mock.csv"
OUTPUT_DIR = WORKSPACE / "public/s14-reports"
OUTPUT_HTML = OUTPUT_DIR / "ota_diagnosis_report_demo.html"
OUTPUT_JSON = OUTPUT_DIR / "s14_result.json"
REPORT_URL = "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html"

@dataclass
class ModuleScore:
    module_id: str
    name: str
    weight: float
    score: float
    reasons: list[str]
    confidence: str

def to_float(value, default=None):
    if value is None: return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value): return default
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"暂无","-","--","null","None"}: return default
    if text.endswith("%"):
        try: return float(text[:-1])/100
        except ValueError: return default
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else default

def pct(v, d=1): return f"{v*100:.{d}f}%" if v is not None else "未获取"
def money(v): return f"{v:,.2f}" if v is not None else "未获取"
def clamp(v, lo=0, hi=1): return max(lo, min(hi, v))
def esc(v): return html.escape("" if v is None else str(v))

def status_class(rate):
    if rate < 0.6: return "bad"
    if rate < 0.8: return "warn"
    return "good"

def status_label(rate):
    if rate < 0.6: return "严重短板"
    if rate < 0.8: return "需要优化"
    return "正常"

def risk_label(score):
    if score < 60: return "高风险"
    if score < 80: return "中风险"
    return "低风险"

# ============ BUILT-IN RULES ============
MODULE_WEIGHTS = {
    "M01": {"名称": "经营结果与收益锚点", "权重": 20},
    "M02": {"名称": "流量曝光与竞争圈", "权重": 15},
    "M03": {"名称": "转化下单与路径断点", "权重": 15},
    "M04": {"名称": "价格收益与房态库存", "权重": 15},
    "M05": {"名称": "推广效率与ROI", "权重": 10},
    "M06": {"名称": "页面展示与入口基础", "权重": 10},
    "M07": {"名称": "口碑信任与服务响应", "权重": 8},
    "M08": {"名称": "执行复盘与数据完整度", "权重": 7},
}

SCORE_RULES = [
    # rid, module, name, points, higher_is_better
    ("V4-001","M01","订单竞争力",4,True),
    ("V4-002","M01","收入环比",4,True),
    ("V4-003","M01","RevPAR趋势",4,True),
    ("V4-004","M01","ADR竞争力",4,True),
    ("V4-005","M01","流失金额控制",4,False),
    ("V4-006","M02","OTA渠道占比",4,False),
    ("V4-007","M02","曝光量趋势",4,True),
    ("V4-008","M02","浏览量趋势",4,True),
    ("V4-009","M02","竞争圈排名",3,True),
    ("V4-012","M03","浏览-下单转化",4,True),
    ("V4-013","M03","下单-支付转化",4,True),
    ("V4-014","M03","支付成功率",4,True),
    ("V4-015","M03","流失挽回率",3,True),
    ("V4-017","M04","房型健康度",5,True),
    ("V4-018","M04","价格竞争力",5,True),
    ("V4-019","M04","库存利用率",5,True),
    ("V4-023","M05","推广ROI",4,True),
    ("V4-024","M05","推广曝光量",2,True),
    ("V4-025","M05","推广点击率",2,True),
    ("V4-026","M05","CPC效率",2,True),
    ("V4-028","M06","图片质量",3,True),
    ("V4-029","M06","视频状态",2,True),
    ("V4-030","M06","房型卖点",2,True),
    ("V4-031","M06","入口标签",3,True),
    ("V4-033","M07","平台评分",3,True),
    ("V4-034","M07","差评率",2,True),
    ("V4-035","M07","回复率",3,True),
    ("V4-038","M08","字段完整度",3,True),
    ("V4-039","M08","整改动作执行",2,True),
    ("V4-040","M08","复盘质量",2,True),
]

CAP_RULES = [
    ("C06","数据可信度封顶：关键经营字段缺失超过30%，总分最高不得超过70"),
    ("C04","转化封顶：转化下单模块低于60%，需优先核查浏览-支付转化"),
    ("C07","基础项封顶：经营结果核心模块低于60%，基础项不能拉高总分"),
    ("C01","收益封顶：RevPAR低于收益基准，总分最高不得超过75"),
]

# ============ BUILD DEMO METRICS ============
def build_demo_metrics(manual: dict) -> dict:
    monthly = [
        {"month":"2026-01","available_room_nights":930,"sold_room_nights":558,"room_revenue":78120,"adr":140.0,"revpar":84.0,"occupancy":0.60,"revenue_mom":None},
        {"month":"2026-02","available_room_nights":840,"sold_room_nights":546,"room_revenue":79170,"adr":145.0,"revpar":94.25,"occupancy":0.65,"revenue_mom":0.0134},
        {"month":"2026-03","available_room_nights":930,"sold_room_nights":651,"room_revenue":91140,"adr":140.0,"revpar":98.0,"occupancy":0.70,"revenue_mom":0.1512},
        {"month":"2026-04","available_room_nights":900,"sold_room_nights":630,"room_revenue":94500,"adr":150.0,"revpar":105.0,"occupancy":0.70,"revenue_mom":0.0369},
        {"month":"2026-05","available_room_nights":930,"sold_room_nights":744,"room_revenue":111600,"adr":150.0,"revpar":120.0,"occupancy":0.80,"revenue_mom":0.1810},
        {"month":"2026-06","available_room_nights":310,"sold_room_nights":201,"room_revenue":28306,"adr":140.83,"revpar":91.31,"occupancy":0.648,"revenue_mom":None},
    ]
    rooms = [
        {"room_type":"至臻·电竞大床房","available_room_nights":10,"room_revenue":9100,"adr":160.0,"occupancy":0.82,"revpar":131.2,"status":"健康房型","suggestion":"保持监控"},
        {"room_type":"至臻·电竞双床房","available_room_nights":8,"room_revenue":7200,"adr":150.0,"occupancy":0.75,"revpar":112.5,"status":"健康房型","suggestion":"保持监控"},
        {"room_type":"独享·电竞单人间","available_room_nights":5,"room_revenue":4500,"adr":130.0,"occupancy":0.70,"revpar":91.0,"status":"中等房型","suggestion":"优化价格策略"},
        {"room_type":"开黑·电竞双床房","available_room_nights":5,"room_revenue":2800,"adr":110.0,"occupancy":0.55,"revpar":60.5,"status":"低效房型","suggestion":"调价或改造"},
        {"room_type":"尊享·电竞套房","available_room_nights":3,"room_revenue":2700,"adr":200.0,"occupancy":0.45,"revpar":90.0,"status":"低效房型","suggestion":"调价或下架"},
    ]
    channels = [
        {"channel":"美团","room_nights":480,"room_revenue":67200,"adr":140.0,"occupancy":0.70},
        {"channel":"飞猪","room_nights":240,"room_revenue":36000,"adr":150.0,"occupancy":0.65},
        {"channel":"携程","room_nights":120,"room_revenue":18000,"adr":150.0,"occupancy":0.62},
        {"channel":"艺龙","room_nights":72,"room_revenue":10080,"adr":140.0,"occupancy":0.58},
        {"channel":"抖音","room_nights":36,"room_revenue":5400,"adr":150.0,"occupancy":0.50},
    ]
    ota_orders = {"订单数量":8,"支付订单":6,"取消订单":2,"订单金额":11200}
    ota_peer = {"同行预订订单":12,"同行间夜单价":145.0,"流失订单数":4,"流失金额":5800}
    ota_promo = {"推广状态":"正常","推广订单金额":4500,"总花费":900,"推广间夜量":3,"首页可见评分":"4.7"}
    ota_missing = [
        {"field":"经营折线趋势数据","status":"缺失","suggestion":"从飞猪后台逐月导出RevPAR/ADR趋势","owner":"OTA运营"},
        {"field":"直通车曝光/点击/CPC","status":"缺失","suggestion":"补采推广明细报表","owner":"OTA运营"},
        {"field":"浏览-支付转化率","status":"缺失","suggestion":"从飞猪经营数据页或直通车后台补齐","owner":"OTA运营"},
        {"field":"竞对价库完整数据","status":"缺失","suggestion":"确认核心竞对实时房价","owner":"收益经理"},
        {"field":"图片质量/HOS历史","status":"部分","suggestion":"补拍首图及电竞设备细节图","owner":"门店店长"},
        {"field":"入口标签质量","status":"部分","suggestion":"完善房型标签和权益描述","owner":"OTA运营"},
        {"field":"流失订单明细","status":"缺失","suggestion":"追踪流失去向和流失原因","owner":"OTA运营"},
    ]
    # 11 core fields: 6 present, 4 missing/partial, 1 partial → ~0.55
    field_completeness = 0.55

    return {
        "monthly": monthly, "latest_month": monthly[-1], "previous_month": monthly[-2],
        "rooms": rooms, "channels": channels,
        "ota_orders": ota_orders, "ota_peer": ota_peer, "ota_promo": ota_promo,
        "ota_missing": ota_missing, "field_completeness": round(field_completeness, 4),
        "manual": manual,
    }

# ============ SCORING ============
def score_ratio(value, target, points, higher_is_better=True):
    if value is None or target in (None, 0): return points * 0.5
    ratio = value / target if higher_is_better else target / value
    return points * clamp(ratio / 1.2)

def compute_scores(metrics: dict) -> tuple[list[ModuleScore], list[str]]:
    latest = metrics["latest_month"]
    prev = metrics["previous_month"]
    peer = metrics["ota_peer"]
    promo = metrics["ota_promo"]
    manual = metrics["manual"]
    rooms = metrics["rooms"]
    orders = metrics["ota_orders"]
    monthly = metrics["monthly"]

    rule_scores: dict[str, tuple[float,str]] = {}
    for rid, mid, name, points, hib in SCORE_RULES:
        score = points * 0.65; reason = f"{name}: 默认评估"
        if rid == "V4-001":
            score = score_ratio(to_float(orders.get("订单数量")), to_float(peer.get("同行预订订单")), points, hib)
            reason = f"{name}: 飞猪订单 {orders.get('订单数量')} vs 同行 {peer.get('同行预订订单')}"
        elif rid == "V4-002":
            mom = latest.get("revenue_mom")
            score = points * (0.95 if mom and mom > 0 else 0.55)
            reason = f"{name}: 收入环比 {pct(mom)}"
        elif rid == "V4-003":
            revpar_avg = sum(m["revpar"] for m in monthly[-3:]) / max(1, len(monthly[-3:]))
            score = score_ratio(latest.get("revpar"), revpar_avg, points, hib)
            reason = f"{name}: RevPAR {latest.get('revpar'):.2f}，近3月均值 {revpar_avg:.2f}"
        elif rid == "V4-004":
            score = score_ratio(latest.get("adr"), to_float(peer.get("同行间夜单价")), points, hib)
            reason = f"{name}: ADR {latest.get('adr'):.2f} vs 同行 {peer.get('同行间夜单价')}"
        elif rid == "V4-005":
            loss = to_float(peer.get("流失金额"), 0) or 0
            score = points * (0.4 if loss > 5000 else (0.7 if loss > 2000 else 0.9))
            reason = f"{name}: 流失金额 {money(loss)}"
        elif rid == "V4-006":
            ota_chs = [c for c in metrics["channels"] if "美团" in c["channel"] or "飞猪" in c["channel"] or "携程" in c["channel"]]
            total_nights = sum(c["room_nights"] for c in metrics["channels"]) or 1
            ota_share = sum(c["room_nights"] for c in ota_chs) / total_nights
            score = points * (0.55 if ota_share > 0.75 else 0.8)
            reason = f"{name}: OTA渠道间夜占比 {pct(ota_share)}"
        elif rid in {"V4-007","V4-008"}:
            score = points * 0.7
            reason = f"{name}: 趋势数据部分补采，按已确认入口暂估"
        elif rid == "V4-009":
            score = points * 0.65
            reason = f"{name}: 竞对排名数据待补采"
        elif rid in {"V4-012","V4-013","V4-014","V4-015"}:
            score = points * 0.45
            reason = f"{name}: 转化趋势/流失数据不完整，按缺口降分"
        elif rid == "V4-017":
            weak = len([r for r in rooms if r["status"] == "低效房型"])
            score = points * (0.55 if weak else 0.85)
            reason = f"{name}: 低效房型 {weak} 个"
        elif rid == "V4-018":
            score = points * 0.7
            reason = f"{name}: 竞对价库待补采，按当前ADR暂估"
        elif rid == "V4-019":
            occ = latest.get("occupancy", 0) or 0
            score = points * clamp(occ / 0.85)
            reason = f"{name}: 出租率 {pct(occ)}"
        elif rid == "V4-023":
            amount = to_float(promo.get("推广订单金额"), 0) or 0
            cost = to_float(promo.get("总花费"), 0) or 0
            roi = amount / cost if cost else None
            score = points * (0.95 if roi and roi >= 5 else (0.7 if roi and roi >= 3 else 0.45))
            reason = f"{name}: 推广ROI {roi:.2f}" if roi else f"{name}: 推广成本缺失"
        elif rid in {"V4-024","V4-025","V4-026"}:
            score = points * (0.45 if rid == "V4-025" else 0.65)
            reason = f"{name}: 推广明细待补采"
        elif rid in {"V4-028","V4-029","V4-030","V4-031"}:
            img = manual.get("image_quality_rating","partial")
            vid = manual.get("video_status","partial")
            rsp = manual.get("room_selling_point_status","partial")
            tag = manual.get("entry_tag_quality","partial")
            complete = sum(1 for x in [img,vid,rsp,tag] if x in {"good","complete"})
            score = points * (0.4 + complete * 0.12)
            reason = f"{name}: 页面质量评分（图片:{img} 视频:{vid} 卖点:{rsp} 标签:{tag})"
        elif rid in {"V4-033","V4-034","V4-035"}:
            rating_str = str(promo.get("首页可见评分","4.0"))
            nums = [to_float(x) for x in re.findall(r"\d+(?:\.\d+)?", rating_str)]
            avg = sum(x for x in nums if x is not None) / max(1, len(nums))
            score = points * clamp(avg / 5)
            reason = f"{name}: 平台评分 {avg:.2f}"
        elif rid == "V4-038":
            fc = metrics["field_completeness"]
            score = points * fc
            reason = f"{name}: 关键字段完整度 {pct(fc)}"
        elif rid in {"V4-039","V4-040"}:
            has_actions = bool(manual.get("completed_actions")) and bool(manual.get("pending_actions"))
            score = points * (0.75 if has_actions else 0.35)
            reason = f"{name}: 模拟表单已提供整改动作和复盘"
        rule_scores[rid] = (score, reason)

    modules: list[ModuleScore] = []
    for mid, mod in MODULE_WEIGHTS.items():
        mod_rules = [(rid,name,pts,hib) for rid,mid2,name,pts,hib in SCORE_RULES if mid2==mid]
        score_sum = sum(rule_scores[r[0]][0] for r in mod_rules)
        weight = mod["权重"]
        score_sum = min(score_sum, weight)
        reasons = []
        for rid, name, pts, _ in mod_rules:
            if rid in rule_scores:
                reasons.append(f"{name}: {rule_scores[rid][1]}")
        fc = metrics["field_completeness"]
        conf = "high" if fc >= 0.8 else ("medium" if fc >= 0.55 else "low")
        modules.append(ModuleScore(mid, mod["名称"], float(weight), round(score_sum,2), reasons[:3], conf))

    caps = []
    if metrics["field_completeness"] < 0.7:
        caps.append("C06 数据可信度封顶：关键经营字段缺失超过30%，总分最高不得超过70。")
    if any(m.module_id=="M03" and m.score/m.weight<0.6 for m in modules):
        caps.append("C04 转化封顶：转化下单模块低于60%，需优先核查浏览-支付转化。")
    if any(m.module_id=="M01" and m.score/m.weight<0.6 for m in modules):
        caps.append("C07 基础项封顶：经营结果核心模块低于60%，基础项不能拉高总分。")
    raw = sum(m.score for m in modules)
    if raw >= 85 and (latest.get("revpar") or 0) < 120:
        caps.append("C01 收益封顶：RevPAR低于收益基准，总分最高不得超过75。")
    return modules, caps

# ============ HTML RENDER ============
def render_table(rows):
    if not rows: return ""
    head = "".join(f"<th>{esc(x)}</th>" for x in rows[0])
    body = "".join("<tr>"+"".join(f"<td>{x}</td>" for x in row)+"</tr>" for row in rows[1:])
    return f"<table class='data-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

def render_trend_chart(revpar_data, adr_data, width=640, height=250):
    if not revpar_data: return ""
    all_pts = revpar_data + adr_data
    mn, mx = min(all_pts), max(all_pts)
    mn -= (mx-mn)*0.1; mx += (mx-mn)*0.1; rng = mx-mn or 1
    pl, pr, pt, pb = 60, 20, 20, 35
    cw, ch = width-pl-pr, height-pt-pb

    def svg_line(pts, color, label):
        coords = []
        circles = []
        for i, val in enumerate(pts):
            x = pl + i*(cw/max(1,len(pts)-1))
            y = pt + ch - ((val-mn)/rng)*ch
            coords.append(f"{x:.1f},{y:.1f}")
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" opacity="0.9"/><circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="white"/>')
        return f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round"/>'+''.join(circles)

    y_ticks = ""
    for i in range(6):
        val = mn + rng*i/5
        y = pt+ch-((val-mn)/rng)*ch
        y_ticks += f'<line x1="{pl-5}" y1="{y:.1f}" x2="{width-pr}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="4,4"/><text x="{pl-10}" y="{y:.1f}" text-anchor="end" dominant-baseline="middle" font-size="11" fill="#6b7280">{val:.0f}</text>'

    return f'''<svg viewBox="0 0 {width} {height}" class="trend-chart">
{y_ticks}
{svg_line(revpar_data, '#2563eb', 'RevPAR')}
{svg_line(adr_data, '#168a4a', 'ADR')}
</svg>'''

def render_html(metrics, module_scores, caps, manual):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw_score = sum(m.score for m in module_scores)
    final_score = raw_score
    cap_labels = []
    for c in caps:
        if "C06" in c: final_score = min(final_score, 70)
        elif "C04" in c: final_score = min(final_score, 82)
        elif "C07" in c: final_score = min(final_score, 80)
        elif "C01" in c: final_score = min(final_score, 75)
        cap_labels.append(c)
    risk = risk_label(final_score)

    monthly = metrics["monthly"]
    rooms = metrics["rooms"]

    # KPI
    kpi_html = f'''<div class="kpi"><label>总分</label><strong class="num">{final_score:.0f} / 100</strong><span>原始分 {raw_score:.1f}</span></div>
<div class="kpi"><label>风险等级</label><strong class="num">{risk}</strong><span>字段完整度 {metrics['field_completeness']*100:.0f}%</span></div>
<div class="kpi"><label>核心问题</label><strong>转化/趋势补采</strong><span>飞猪经营折线、直通车CPC未完整采集</span></div>
<div class="kpi"><label>复盘周期</label><strong class="num">7 / 14 天</strong><span>复盘日期：{esc(manual.get('review_date',''))}</span></div>'''

    cap_items = "".join(f"<li>{esc(c)}</li>" for c in cap_labels) or "<li>本次未触发强封顶</li>"

    # Module scores
    mod_rows = [["模块","得分","得分率","状态","核心依据"]]
    for m in module_scores:
        rate = m.score/m.weight if m.weight else 0
        mod_rows.append([
            f"{m.module_id} {esc(m.name)}",
            f"{m.score:.1f} / {m.weight:.0f}",
            f"{rate*100:.0f}%",
            f"<span class='status {status_class(rate)}'>{status_label(rate)}</span>",
            "<br>".join(esc(r) for r in m.reasons),
        ])

    # Trend
    trend_rows = [["月份","ADR","出租率","RevPAR","门店收入","收入环比"]]
    for m in monthly:
        trend_rows.append([m["month"],f"{m['adr']:.2f}",pct(m['occupancy']),f"{m['revpar']:.2f}",money(m['room_revenue']),pct(m['revenue_mom']) if m['revenue_mom'] is not None else "首月"])

    # Rooms
    room_rows = [["房型名称","房数","平均房价","出租率","RevPAR","状态","建议"]]
    for r in rooms:
        cls = "bad" if r["status"]=="低效房型" else ("warn" if r["status"]=="中等房型" else "good")
        room_rows.append([esc(r["room_type"]),f"{r['available_room_nights']:.0f}",f"{r['adr']:.2f}",f"<span class='status {cls}'>{pct(r['occupancy'])}</span>",f"{r['revpar']:.2f}",f"<span class='status {cls}'>{esc(r['status'])}</span>",esc(r["suggestion"])])

    # Funnel (fliggy)
    orders = metrics["ota_orders"]
    peer = metrics["ota_peer"]
    funnel_rows = [["数据项","当前值","口径","判断"]]
    funnel_rows += [
        ["飞猪预订订单量",esc(orders.get("订单数量","未获取")),"飞猪经营数据","订单结果"],
        ["同行预订订单",esc(peer.get("同行预订订单","未获取")),"飞猪竞争圈","竞争对比"],
        ["流失订单数",esc(peer.get("流失订单数","未获取")),"统计周期内","流失损失"],
        ["流失金额",esc(peer.get("流失金额","未获取")),"统计周期内","影响收益"],
        ["经营折线趋势","待补采","飞猪经营数据页","数据缺口"],
    ]

    # Promotion
    promo = metrics["ota_promo"]
    pa = to_float(promo.get("推广订单金额"),0) or 0
    pc = to_float(promo.get("总花费"),0) or 0
    proi = pa/pc if pc else None
    promo_rows = [["指标","值","口径","判断"]]
    promo_rows += [
        ["推广状态",esc(promo.get("推广状态","正常")),"飞猪全网推","推广开关"],
        ["推广订单金额",money(pa),"近30日","推广产出"],
        ["推广间夜量",esc(promo.get("推广间夜量","未获取")),"近30日","推广产出"],
        ["总花费",money(pc),"近30日","推广成本"],
        ["ROI",f"{proi:.2f}" if proi else "未获取","订单金额/总花费","ROI高但CPC缺失"],
    ]

    # Tasks
    task_rows = [["优先级","负责人","整改动作","复盘指标","周期"]]
    task_rows += [
        ["P0","OTA运营","补采飞猪经营趋势和直通车CPC","字段完整度、转化率","3天"],
        ["P0","OTA运营","检查房型权益/活动价/退改规则","浏览-支付转化率","7天"],
        ["P1","收益经理","复盘低效房型价格和库存","房型RevPAR、出租率","7天"],
        ["P1","门店店长","补拍首图/电竞细节/房型差异图","详情页浏览、转化率","14天"],
        ["P2","运营负责人","建立整改动作日志和复盘机制","动作完成率、收入","14天"],
    ]

    # Missing
    missing_rows = [["缺失字段","当前状态","处理建议","责任来源"]]
    for m in metrics["ota_missing"]:
        missing_rows.append([esc(m["field"]),esc(m["status"]),esc(m["suggestion"]),esc(m["owner"])])

    return f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>酒店 OTA 全面诊断报告</title>
<style>
:root {{ --bg:#f6f7f9;--panel:#fff;--ink:#1d2430;--muted:#667085;--line:#d9dee8;--blue:#2563eb;--green:#168a4a;--amber:#b7791f;--red:#c2413a;--shadow:0 8px 24px rgba(22,34,51,.08); }}
* {{ box-sizing:border-box; }}
body {{ margin:0;background:var(--bg);color:var(--ink);font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6; }}
.app-header {{ background:var(--panel);border-bottom:1px solid var(--line);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px; }}
.app-header h1 {{ margin:0;font-size:20px; }}
.app-header p {{ margin:4px 0 0;color:var(--muted);font-size:13px; }}
.layout {{ display:flex;max-width:1200px;margin:0 auto;padding:20px;gap:20px; }}
.sidebar {{ width:180px;flex-shrink:0;position:sticky;top:20px;align-self:flex-start; }}
.sidebar a {{ display:block;padding:8px 12px;color:var(--ink);text-decoration:none;font-size:13px;border-radius:6px; }}
.sidebar a:hover {{ background:#edf0f5;color:var(--blue); }}
main {{ flex:1;min-width:0; }}
section {{ background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:16px;overflow:hidden; }}
.section-head {{ display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--line); }}
.section-head h2 {{ margin:0;font-size:16px; }}
.section-head p {{ margin:4px 0 0;color:var(--muted);font-size:12px; }}
.section-body {{ padding:16px 18px; }}
.kpi-grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px; }}
.kpi {{ padding:14px;border:1px solid var(--line);border-radius:8px; }}
.kpi label {{ font-size:12px;color:var(--muted);display:block;margin-bottom:4px; }}
.kpi .num {{ font-size:28px;font-weight:700;display:block; }}
.kpi span {{ font-size:12px;color:var(--muted);display:block;margin-top:4px; }}
.cap-alert {{ margin-top:14px;padding:12px 14px;background:#fff8e6;border:1px solid #f0c75e;border-radius:8px;font-size:13px; }}
.cap-alert ul {{ margin:6px 0 0;padding-left:18px; }}
.data-table {{ width:100%;border-collapse:collapse;font-size:13px; }}
.data-table th,.data-table td {{ border:1px solid var(--line);padding:8px 10px;text-align:left; }}
.data-table th {{ background:#f8f9fb;font-weight:600; }}
.status {{ display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600; }}
.status.good {{ background:#d4edda;color:#155724; }}
.status.warn {{ background:#fff3cd;color:#856404; }}
.status.bad {{ background:#f8d7da;color:#721c24; }}
.two-col {{ display:grid;grid-template-columns:1fr 1fr;gap:16px; }}
.trend-chart {{ width:100%;height:auto;max-height:260px; }}
.legend {{ display:flex;gap:16px;margin-top:8px;font-size:12px; }}
.legend i {{ display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:middle; }}
.btn {{ padding:8px 16px;border-radius:6px;border:1px solid var(--line);background:var(--panel);cursor:pointer;font-size:13px; }}
.btn.primary {{ background:var(--blue);color:#fff;border-color:var(--blue); }}
@media (max-width:768px) {{ .layout{{flex-direction:column;}} .sidebar{{display:none;}} .two-col{{grid-template-columns:1fr;}} }}
</style></head>
<body>
<header class="app-header"><div>
<h1>酒店 OTA 全面诊断报告</h1>
<p>{esc(manual.get('hotel_name','贵阳璞悦·奢电竞酒店'))} ｜ 周期：{esc(manual.get('period_start',''))} 至 {esc(manual.get('period_end',''))} ｜ 渠道：{esc(manual.get('channel_source','飞猪'))} ｜ 生成时间：{now}</p>
</div><div><button class="btn primary" onclick="window.print()">导出报告</button></div></header>
<div class="layout">
<nav class="sidebar">
<a href="#overview">总览卡片</a><a href="#modules">模块得分</a><a href="#trend">经营趋势</a><a href="#funnel">流量漏斗</a><a href="#rooms">房型排行</a><a href="#promotion">推广效率</a><a href="#tasks">整改任务</a><a href="#missing">补采提示</a>
</nav>
<main>
<section id="overview"><div class="section-head"><div><h2>顶部总览卡片</h2><p>规则来自酒店OTA全面诊断系统开发交付文档，当前为测试环境演示报告</p></div><span class="status {status_class(final_score/100)}">{risk}</span></div>
<div class="section-body"><div class="kpi-grid">{kpi_html}</div>
<div class="cap-alert"><b>封顶/校准规则</b><ul>{cap_items}</ul><span class="status warn">按交付表校准</span></div></div></section>

<section id="modules"><div class="section-head"><h2>模块得分</h2></div><div class="section-body">{render_table(mod_rows)}</div></section>

<section id="trend"><div class="section-head"><h2>经营趋势图</h2></div><div class="section-body two-col"><div><h3 style="margin-top:0">月度经营趋势</h3>{render_trend_chart([m["revpar"] for m in monthly],[m["adr"] for m in monthly])}<div class="legend"><span><i style="background:#2563eb"></i>RevPAR</span><span><i style="background:#168a4a"></i>ADR</span></div></div><div><h3 style="margin-top:0">月度经营数据</h3>{render_table(trend_rows)}</div></div></section>

<section id="funnel"><div class="section-head"><h2>流量漏斗（飞猪）</h2><span class="status bad">趋势未完整</span></div><div class="section-body">{render_table(funnel_rows)}</div></section>

<section id="rooms"><div class="section-head"><h2>房型排行</h2></div><div class="section-body">{render_table(room_rows)}</div></section>

<section id="promotion"><div class="section-head"><h2>推广效率（飞猪）</h2><span class="status warn">CPC缺失</span></div><div class="section-body">{render_table(promo_rows)}</div></section>

<section id="tasks"><div class="section-head"><h2>整改任务表</h2></div><div class="section-body">{render_table(task_rows)}</div></section>

<section id="missing"><div class="section-head"><h2>补采提示</h2></div><div class="section-body">{render_table(missing_rows)}</div></section>

</main></div>
<footer style="text-align:center;padding:20px;color:var(--muted);font-size:12px">
S14 酒店OTA全面诊断报告 ｜ 测试环境 ｜ 数据来源: local_table_mode/demo ｜ 计算公式: runtime/calculator.py<br>
当前为 S14 测试机器人返回结果，不影响正式 hotel-ota-ai Agent
</footer>
</body></html>'''

def main():
    # Read manual form
    manual: dict[str,str] = {}
    field_map = {
        "酒店名称":"hotel_name","开始日期":"period_start","结束日期":"period_end",
        "渠道来源":"channel_source","可用房数":"available_rooms","可售间夜":"available_room_nights",
        "PMS房费收入":"pms_room_revenue","PMS已售间夜":"pms_sold_room_nights",
        "图片质量评级":"image_quality_rating","视频状态":"video_status",
        "房型卖点状态":"room_selling_point_status","入口标签质量":"entry_tag_quality",
        "已完成动作":"completed_actions","待完成动作":"pending_actions",
        "负责人":"owner_user_id","复盘日期":"review_date",
        "异常事件":"abnormal_events","异常原因":"abnormal_reason",
    }
    with MANUAL_FORM.open("r",encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            fn = row.get("field","")
            if fn in field_map:
                manual[field_map[fn]] = row.get("value","")
            else:
                manual[fn] = row.get("value","")
    manual.setdefault("hotel_name","贵阳璞悦·奢电竞酒店")
    manual.setdefault("period_start","2026-06-01")
    manual.setdefault("period_end","2026-06-10")
    manual.setdefault("channel_source","飞猪")

    # Build metrics
    metrics = build_demo_metrics(manual)

    # Compute scores
    module_scores, caps = compute_scores(metrics)

    # Render HTML
    html = render_html(metrics, module_scores, caps, manual)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"HTML report written: {OUTPUT_HTML}")

    # Final score
    raw_score = sum(m.score for m in module_scores)
    final_score = raw_score
    for c in caps:
        if "C06" in c: final_score = min(final_score, 70)
        elif "C04" in c: final_score = min(final_score, 82)
        elif "C07" in c: final_score = min(final_score, 80)
        elif "C01" in c: final_score = min(final_score, 75)

    result = {
        "status": "partial" if caps else "ok",
        "skill_id": "s14-operation-diagnosis",
        "data_source": "demo_generated",
        "mode": "standalone_demo",
        "raw_score": round(raw_score, 2),
        "final_score": round(final_score, 2),
        "risk_level": risk_label(final_score),
        "field_completeness": metrics["field_completeness"],
        "module_scores": [
            {"module_id":m.module_id,"name":m.name,"weight":m.weight,"score":m.score,"confidence":m.confidence}
            for m in module_scores
        ],
        "triggered_caps": caps,
        "report_url": REPORT_URL,
        "report_file_path": str(OUTPUT_HTML),
        "generated_at": datetime.now().isoformat(),
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
