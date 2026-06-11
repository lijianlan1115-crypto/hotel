#!/usr/bin/env python3
"""S14 diagnosis using real MySQL data. Reads hotel_pricing tables directly."""
from __future__ import annotations
import html, json, math, os, re, sys
from datetime import datetime, date
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pymysql

WORKSPACE = Path("/opt/openclaw/workspaces/s14-feishu-test")
OUTPUT_DIR = Path("/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports")
OUTPUT_HTML = OUTPUT_DIR / "ota_diagnosis_report_demo.html"
REPORT_URL = "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html"

HOTEL_ID = "puyue"
PERIOD_START = "2026-06-01"
PERIOD_END = "2026-06-10"
PLATFORM = "meituan"  # primary platform for filtering

@dataclass
class ModuleScore:
    module_id: str; name: str; weight: float; score: float; reasons: list[str]; confidence: str

def to_float(v, d=None):
    if v is None: return d
    if isinstance(v,(int,float)):
        if isinstance(v,float) and math.isnan(v): return d
        return float(v)
    t=str(v).strip().replace(",","")
    if not t or t in {"暂无","-","--","null","None"}: return d
    if t.endswith("%"):
        try: return float(t[:-1])/100
        except: return d
    m=re.search(r"-?\d+(?:\.\d+)?",t)
    return float(m.group()) if m else d

def pct(v,d=1): return f"{v*100:.{d}f}%" if v is not None else "无数据"
def money(v): return f"{v:,.2f}" if v is not None else "无数据"
def clamp(v,lo=0,hi=1): return max(lo,min(hi,v))
def esc(v): return html.escape("" if v is None else str(v))
def sc(rate):
    if rate<0.6: return "bad"
    if rate<0.8: return "warn"
    return "good"
def sl(rate):
    if rate<0.6: return "严重短板"
    if rate<0.8: return "需优化"
    return "正常"
def rl(score):
    if score<60: return "高风险"
    if score<80: return "中风险"
    return "低风险"

# ======================== DATABASE ========================
def get_conn():
    dsn = os.environ.get("HOTEL_OTA_DB_DSN","")
    if not dsn: raise RuntimeError("HOTEL_OTA_DB_DSN not set")
    p = urlparse(dsn)
    return pymysql.connect(host=p.hostname,port=p.port or 3306,user=p.username,
        password=p.password,database=p.path.lstrip("/"),charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor)

def fetch_daily_metrics(conn, hotel_name: str) -> dict:
    """Read fact_daily_metrics EAV table, convert to column dict."""
    cur = conn.cursor()
    cur.execute("""
        SELECT business_date, metric_group, metric_item, metric_name, metric_value, period_type
        FROM fact_daily_metrics
        WHERE hotel_name = %s AND business_date BETWEEN %s AND %s
        ORDER BY business_date, metric_group, metric_item, metric_name
    """, (hotel_name, PERIOD_START, PERIOD_END))
    rows = cur.fetchall()
    
    # Convert EAV to dict keyed by (date, metric_name)
    metrics_by_date: dict[str, dict] = {}
    for r in rows:
        d = str(r["business_date"])
        if d not in metrics_by_date:
            metrics_by_date[d] = {}
        name = str(r["metric_name"])
        val = to_float(r["metric_value"])
        metrics_by_date[d][name] = val
    
    # Aggregate
    dates = sorted(metrics_by_date.keys())
    daily_records = []
    for d in dates:
        m = metrics_by_date[d]
        daily_records.append({
            "date": d,
            "room_revenue": m.get("房费") or m.get("room_fee"),
            "adr": m.get("平均房价") or m.get("adr"),
            "occupancy": (m.get("过夜房出租率") or m.get("出租率") or m.get("occupancy_rate") or 0) / 100 if (m.get("过夜房出租率") or m.get("出租率") or m.get("occupancy_rate")) else None,
            "room_nights": m.get("过夜房") or m.get("间夜数") or m.get("room_nights"),
            "revpar": m.get("RevPar") or m.get("revpar"),
            "available_rooms": m.get("客房数") or 31,
        })
    return daily_records

def fetch_operating_snapshot(conn, hotel_name: str) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM operating_snapshot
        WHERE hotel_name = %s AND business_date = (SELECT MAX(business_date) FROM operating_snapshot WHERE hotel_name = %s)
        LIMIT 1
    """, (hotel_name, hotel_name))
    row = cur.fetchone()
    if not row: return {}
    return {
        "business_date": str(row.get("business_date","")),
        "occupancy_rate": to_float(row.get("occupancy_rate")),
        "adr": to_float(row.get("adr")),
        "revpar": to_float(row.get("revpar")),
        "available_rooms": to_float(row.get("available_rooms")),
        "sold_rooms": to_float(row.get("sold_rooms")),
        "orders_today": to_float(row.get("orders_today")),
    }

def fetch_price_data(conn, hotel_name: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM price_data
        WHERE hotel_name = %s AND business_date = (SELECT MAX(business_date) FROM price_data WHERE hotel_name = %s)
    """, (hotel_name, hotel_name))
    return cur.fetchall()

def fetch_room_fee_daily(conn, hotel_name: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT business_date, room_type, customer_source, daily_price, room_fee, room_nights
        FROM fact_room_fee_daily
        WHERE hotel_name = %s AND business_date BETWEEN %s AND %s
        ORDER BY business_date
    """, (hotel_name, PERIOD_START, PERIOD_END))
    return cur.fetchall()

def fetch_operation_diagnosis(conn, hotel_name: str) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM operation_diagnosis
        WHERE hotel_name = %s ORDER BY business_date DESC LIMIT 1
    """, (hotel_name,))
    return cur.fetchone() or {}

# ======================== SCORING ========================
MODULE_WEIGHTS = {
    "M01": ("经营结果与收益锚点",20),
    "M02": ("流量曝光与竞争圈",15),
    "M03": ("转化下单与路径断点",15),
    "M04": ("价格收益与房态库存",15),
    "M05": ("推广效率与ROI",10),
    "M06": ("页面展示与入口基础",10),
    "M07": ("口碑信任与服务响应",8),
    "M08": ("执行复盘与数据完整度",7),
}

SCORE_RULES = [
    ("V4-001","M01","订单竞争力",4),
    ("V4-002","M01","收入环比",4),
    ("V4-003","M01","RevPAR趋势",4),
    ("V4-004","M01","ADR竞争力",4),
    ("V4-005","M01","流失控制",4),
    ("V4-006","M02","OTA渠道占比",4),
    ("V4-007","M02","曝光量趋势",4),
    ("V4-008","M02","浏览量趋势",4),
    ("V4-009","M02","竞争圈排名",3),
    ("V4-012","M03","浏览-下单转化",4),
    ("V4-013","M03","下单-支付转化",4),
    ("V4-014","M03","支付成功率",4),
    ("V4-015","M03","流失挽回率",3),
    ("V4-017","M04","房型健康度",5),
    ("V4-018","M04","价格竞争力",5),
    ("V4-019","M04","库存利用率",5),
    ("V4-023","M05","推广ROI",4),
    ("V4-024","M05","推广曝光量",2),
    ("V4-025","M05","推广点击率",2),
    ("V4-026","M05","CPC效率",2),
    ("V4-028","M06","图片质量",3),
    ("V4-029","M06","视频状态",2),
    ("V4-030","M06","房型卖点",2),
    ("V4-031","M06","入口标签",3),
    ("V4-033","M07","平台评分",3),
    ("V4-034","M07","差评率",2),
    ("V4-035","M07","回复率",3),
    ("V4-038","M08","字段完整度",3),
    ("V4-039","M08","整改动作",2),
    ("V4-040","M08","复盘质量",2),
]

def score_ratio(value, target, points):
    if value is None or target in (None,0): return points*0.5
    return points*clamp((value/target)/1.2)

def compute(metrics: dict, op_diag: dict) -> tuple[list[ModuleScore], list[str]]:
    daily = metrics["daily_records"]
    op = metrics["operating"]
    prices = metrics["prices"]
    field_comp = metrics["field_completeness"]
    
    latest_daily = daily[-1] if daily else {}
    has_daily = len(daily) >= 3
    
    # Price analysis
    price_by_room = {}
    for p in prices:
        rt = str(p.get("room_type_id",""))
        ch = str(p.get("channel",""))
        cp = to_float(p.get("current_price"))
        comp = to_float(p.get("competitor_price"))
        if rt not in price_by_room:
            price_by_room[rt] = {"channels": {}, "current": cp, "competitor": comp}
        price_by_room[rt]["channels"][ch] = {"current": cp, "competitor": comp}
    
    above_comp = sum(1 for pr in price_by_room.values() if pr.get("current") and pr.get("competitor") and pr["current"] > pr["competitor"])
    total_rooms = len(price_by_room) or 1
    
    # Recent ADR/RevPAR
    recent_adr = latest_daily.get("adr") or op.get("adr") or 0
    recent_revpar = latest_daily.get("revpar") or op.get("revpar") or 0
    recent_occ = latest_daily.get("occupancy") or op.get("occupancy_rate") or 0
    
    # Trend
    revpar_trend = [d.get("revpar") or 0 for d in daily[-3:]] if has_daily else [recent_revpar]
    adr_trend = [d.get("adr") or 0 for d in daily[-3:]] if has_daily else [recent_adr]
    revpar_avg3 = sum(revpar_trend)/max(1,len(revpar_trend))
    
    # Revenue MoM
    revenues = [d.get("room_revenue") or 0 for d in daily]
    revenue_mom = (revenues[-1]-revenues[-2])/revenues[-2] if len(revenues)>=2 and revenues[-2] else None

    rule_scores: dict[str, tuple[float,str]] = {}
    for rid, mid, name, pts in SCORE_RULES:
        score = pts*0.65; reason = f"{name}: 默认评估"
        
        if rid=="V4-001":
            orders = op.get("orders_today") or 0
            score = pts*clamp(orders/15)
            reason = f"{name}: 当日订单 {orders:.0f} 单"
        elif rid=="V4-002":
            score = pts*(0.95 if revenue_mom and revenue_mom>0 else (0.7 if revenue_mom and revenue_mom>-0.1 else 0.45))
            reason = f"{name}: 收入环比 {pct(revenue_mom)}"
        elif rid=="V4-003":
            score = score_ratio(recent_revpar, revpar_avg3, pts)
            reason = f"{name}: RevPAR {recent_revpar:.2f} vs 近3日均 {revpar_avg3:.2f}"
        elif rid=="V4-004":
            score = pts*(0.85 if recent_adr>130 else (0.7 if recent_adr>100 else 0.5))
            reason = f"{name}: ADR {recent_adr:.2f}"
        elif rid=="V4-005":
            score = pts*0.65
            reason = f"{name}: 流失数据待补采"
        elif rid=="V4-006":
            score = pts*0.75
            reason = f"{name}: OTA渠道占比（美团为主，约80%+）"
        elif rid in {"V4-007","V4-008"}:
            score = pts*(0.8 if op_diag.get("exposure") else 0.5)
            exp = to_float(op_diag.get("exposure"))
            reason = f"{name}: 曝光数据 {'已采集' if exp else '待补采'}"
        elif rid=="V4-009":
            pr = to_float(op_diag.get("peer_rank"))
            score = pts*(0.9 if pr and pr<=3 else (0.7 if pr else 0.5))
            reason = f"{name}: 竞争圈排名 {'第'+str(int(pr))+'名' if pr else '待补采'}"
        elif rid in {"V4-012","V4-013","V4-014","V4-015"}:
            pcr = to_float(op_diag.get("payment_conversion_rate"))
            score = pts*(0.85 if pcr and pcr>0.15 else (0.6 if pcr else 0.45))
            reason = f"{name}: 支付转化 {pct(pcr) if pcr else '待补采'}"
        elif rid=="V4-017":
            weak = sum(1 for pr in price_by_room.values() if pr.get("current") and pr.get("competitor") and pr["current"]<pr["competitor"]*0.9)
            score = pts*(0.55 if weak>2 else (0.75 if weak>0 else 0.85))
            reason = f"{name}: 低于竞对90%的房型 {weak} 个"
        elif rid=="V4-018":
            score = pts*(0.8 if above_comp/total_rooms>0.3 else (0.6 if above_comp>0 else 0.45))
            reason = f"{name}: 高于竞对价的房型 {above_comp}/{total_rooms}"
        elif rid=="V4-019":
            score = pts*clamp(recent_occ/0.85) if recent_occ else pts*0.5
            reason = f"{name}: 出租率 {pct(recent_occ)}"
        elif rid in {"V4-023","V4-024","V4-025","V4-026"}:
            score = pts*0.5
            reason = f"{name}: 推广数据待补采"
        elif rid in {"V4-028","V4-029","V4-030","V4-031"}:
            hos = to_float(op_diag.get("hos_score"), 3.0)
            score = pts*clamp(hos/5)
            reason = f"{name}: HOS/页面质量评分 {hos:.1f}"
        elif rid in {"V4-033","V4-034","V4-035"}:
            rt = to_float(op_diag.get("rating_total"), 4.0)
            br = to_float(op_diag.get("bad_review_rate"), 0.05)
            score = pts*clamp((rt/5)-(br*2))
            reason = f"{name}: 评分 {rt:.1f}，差评率 {pct(br)}"
        elif rid=="V4-038":
            score = pts*field_comp
            reason = f"{name}: 字段完整度 {pct(field_comp)}"
        elif rid in {"V4-039","V4-040"}:
            score = pts*0.6
            reason = f"{name}: 数据库有待补充"
        rule_scores[rid] = (score, reason)

    modules: list[ModuleScore] = []
    for mid, (mname, weight) in MODULE_WEIGHTS.items():
        mod_rules = [(rid,name,pts) for rid,mid2,name,pts in SCORE_RULES if mid2==mid]
        score_sum = sum(rule_scores[rid][0] for rid,_,_ in mod_rules)
        score_sum = min(score_sum, float(weight))
        reasons = [f"{name}: {rule_scores[rid][1]}" for rid,name,_ in mod_rules[:3]]
        conf = "high" if field_comp>=0.8 else ("medium" if field_comp>=0.55 else "low")
        modules.append(ModuleScore(mid, mname, float(weight), round(score_sum,2), reasons, conf))

    caps = []
    if field_comp<0.7:
        caps.append("C06 数据可信度封顶：关键字段缺失>30%，总分≤70")
    if any(m.module_id=="M03" and m.score/m.weight<0.6 for m in modules):
        caps.append("C04 转化封顶：转化模块<60%")
    if any(m.module_id=="M01" and m.score/m.weight<0.6 for m in modules):
        caps.append("C07 基础项封顶：经营模块<60%")
    raw = sum(m.score for m in modules)
    if raw>=85 and recent_revpar<120:
        caps.append("C01 收益封顶：RevPAR<120，总分≤75")
    return modules, caps

# ======================== REPORT ========================
def render_table(rows):
    if not rows: return ""
    head = "".join(f"<th>{esc(x)}</th>" for x in rows[0])
    body = "".join("<tr>"+"".join(f"<td>{x}</td>" for x in row)+"</tr>" for row in rows[1:])
    return f"<table class='dt'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

def render_trend_chart(revpar_data, adr_data, width=640, height=250):
    if not revpar_data: return ""
    all_pts = [x for x in revpar_data+adr_data if x]
    if not all_pts: return ""
    mn,mx = min(all_pts),max(all_pts)
    mn-=(mx-mn)*0.1; mx+=(mx-mn)*0.1; rng=mx-mn or 1
    pl,pr,pt,pb=60,20,20,35; cw,ch=width-pl-pr,height-pt-pb
    def svg_line(pts,color):
        coords=[]; circles=[]
        for i,val in enumerate(pts):
            if not val: val=0
            x=pl+i*(cw/max(1,len(pts)-1)); y=pt+ch-((val-mn)/rng)*ch
            coords.append(f"{x:.1f},{y:.1f}")
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        return f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3"/>'+''.join(circles)
    yt=""
    for i in range(6):
        val=mn+rng*i/5; y=pt+ch-((val-mn)/rng)*ch
        yt+=f'<line x1="{pl-5}" y1="{y:.1f}" x2="{width-pr}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="4,4"/><text x="{pl-10}" y="{y:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{val:.0f}</text>'
    return f'<svg viewBox="0 0 {width} {height}" class="tc">{yt}{svg_line(revpar_data,"#2563eb")}{svg_line(adr_data,"#168a4a")}</svg>'

def generate_report(metrics, modules, caps, hotel_name, op_diag):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = sum(m.score for m in modules)
    final = raw
    for c in caps:
        if "C06" in c: final=min(final,70)
        elif "C04" in c: final=min(final,82)
        elif "C07" in c: final=min(final,80)
        elif "C01" in c: final=min(final,75)
    risk = rl(final)
    daily = metrics["daily_records"]
    prices = metrics["prices"]
    op = metrics["operating"]
    fc = metrics["field_completeness"]

    # KPI
    kpi = f'''<div class="kpi"><label>总分</label><strong class="num">{final:.0f} / 100</strong><span>原始分 {raw:.1f}</span></div>
<div class="kpi"><label>风险</label><strong class="num">{risk}</strong><span>字段完整度 {fc*100:.0f}%</span></div>
<div class="kpi"><label>今日经营</label><strong>出租 {pct(op.get('occupancy_rate'))}</strong><span>ADR ¥{op.get('adr',0):.0f} | 订单 {op.get('orders_today',0):.0f}单</span></div>
<div class="kpi"><label>数据日期</label><strong class="num">{op.get('business_date','未知')}</strong><span>来源: hotel_pricing MySQL</span></div>'''

    caps_html = "".join(f"<li>{esc(c)}</li>" for c in caps) or "<li>未触发封顶</li>"

    # Modules
    mr = [["模块","得分","得分率","状态","核心依据"]]
    for m in modules:
        rate=m.score/m.weight if m.weight else 0
        mr.append([f"{m.module_id} {esc(m.name)}",f"{m.score:.1f} / {m.weight:.0f}",f"{rate*100:.0f}%",
            f"<span class='s {sc(rate)}'>{sl(rate)}</span>","<br>".join(esc(r) for r in m.reasons)])

    # Daily trend
    tr = [["日期","ADR","出租率","RevPAR","房费收入"]]
    for d in daily:
        tr.append([d["date"],f"{d.get('adr',0):.2f}",pct(d.get('occupancy')),f"{d.get('revpar',0):.2f}",money(d.get('room_revenue'))])

    # Price comparison
    pr_rows = [["房型","渠道","当前价","竞对价","价差","判断"]]
    for p in prices[:15]:
        cp=to_float(p.get("current_price")); comp=to_float(p.get("competitor_price"))
        gap=(cp-comp)/comp*100 if cp and comp else None
        cls=sc(0.9) if gap and gap>0 else sc(0.6)
        pr_rows.append([esc(p.get("room_type_id","")),esc(p.get("channel","")),
            f"¥{cp:.2f}" if cp else "-",f"¥{comp:.2f}" if comp else "-",
            f"{gap:+.1f}%" if gap is not None else "-",
            f"<span class='s {cls}'>{'高于竞对' if gap and gap>0 else '低于竞对'}</span>"])

    # HOS / OTA health
    hos_rows = [["指标","值","说明"]]
    hos_rows.append(["HOS/MCI评分",esc(op_diag.get("hos_score","未获取")),"平台服务质量分"])
    hos_rows.append(["商户运营分",esc(op_diag.get("merchant_operation_score","未获取")),"运营健康度"])
    hos_rows.append(["竞争圈排名",f"第{int(to_float(op_diag.get('peer_rank'),0))}名" if op_diag.get("peer_rank") else "未获取","同行排名"])
    hos_rows.append(["曝光量",esc(op_diag.get("exposure","未获取")),"列表页曝光"])
    hos_rows.append(["浏览量",esc(op_diag.get("views","未获取")),"详情页浏览"])
    hos_rows.append(["支付转化率",pct(to_float(op_diag.get("payment_conversion_rate"))) if op_diag.get("payment_conversion_rate") else "未获取","浏览→支付"])
    hos_rows.append(["平台评分",esc(op_diag.get("rating_total","未获取")),"用户评价均分"])
    hos_rows.append(["差评率",pct(to_float(op_diag.get("bad_review_rate"))) if op_diag.get("bad_review_rate") else "未获取","低分评价占比"])

    # Tasks
    tk = [["优先级","负责人","整改动作","周期"]]
    tk.append(["P0","OTA运营","补采美团推广参谋曝光/点击/CPC数据","3天"])
    tk.append(["P0","OTA运营","检查房型定价策略，差异化管理竞对价差","7天"])
    tk.append(["P1","收益经理","分析低出租率房型原因，优化价格或下架","7天"])
    tk.append(["P1","门店店长","补充页面图片和房型标签","14天"])
    tk.append(["P2","运营负责人","建立日报/周报复盘机制","14天"])

    # Missing
    ms = [["缺失字段","影响模块","建议"]]
    missing_items = [
        ("美团推广参谋数据(曝光/点击/CPC)","M05","从美团EBK后台导出推广报表"),
        ("流量转化漏斗(浏览-下单-支付)","M03","接入美团商家版或推广参谋API"),
        ("竞对实时价库","M02/M04","每日采集核心竞对价格"),
        ("房型图片/视频质量","M06","补拍首图及电竞设备细节"),
        ("流失订单明细","M02/M03","追踪竞对流失原因"),
        ("整改动作日志","M08","建立周度复盘记录"),
    ]
    for fld, mod, sug in missing_items:
        ms.append([fld, mod, sug])

    style = """:root{--bg:#f6f7f9;--p:#fff;--i:#1d2430;--m:#667085;--l:#d9dee8;--b:#2563eb;--g:#168a4a;--a:#b7791f;--r:#c2413a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--i);font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
.hd{background:var(--p);border-bottom:1px solid var(--l);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
.hd h1{margin:0;font-size:20px}.hd p{margin:4px 0 0;color:var(--m);font-size:13px}
.ly{display:flex;max-width:1200px;margin:0 auto;padding:20px;gap:20px}
.sb{width:180px;flex-shrink:0;position:sticky;top:20px;align-self:flex-start}
.sb a{display:block;padding:8px 12px;color:var(--i);text-decoration:none;font-size:13px;border-radius:6px}
.sb a:hover{background:#edf0f5;color:var(--b)}
main{flex:1;min-width:0}
.sec{background:var(--p);border:1px solid var(--l);border-radius:10px;margin-bottom:16px;overflow:hidden}
.sh{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--l)}
.sh h2{margin:0;font-size:16px}.sh p{margin:4px 0 0;color:var(--m);font-size:12px}
.sb2{padding:16px 18px}
.kg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{padding:14px;border:1px solid var(--l);border-radius:8px}
.kpi label{font-size:12px;color:var(--m);display:block;margin-bottom:4px}
.kpi .num{font-size:28px;font-weight:700;display:block}
.kpi span{font-size:12px;color:var(--m);display:block;margin-top:4px}
.ca{margin-top:14px;padding:12px 14px;background:#fff8e6;border:1px solid #f0c75e;border-radius:8px;font-size:13px}
.ca ul{margin:6px 0 0;padding-left:18px}
.dt{width:100%;border-collapse:collapse;font-size:13px}
.dt th,.dt td{border:1px solid var(--l);padding:8px 10px;text-align:left}
.dt th{background:#f8f9fb;font-weight:600}
.s{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}
.s.good{background:#d4edda;color:#155724}.s.warn{background:#fff3cd;color:#856404}.s.bad{background:#f8d7da;color:#721c24}
.tc{width:100%;height:auto;max-height:260px}
.lg{display:flex;gap:16px;margin-top:8px;font-size:12px}
.lg i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:middle}
.btn{padding:8px 16px;border-radius:6px;border:1px solid var(--l);background:var(--p);cursor:pointer;font-size:13px}
.btn.p{background:var(--b);color:#fff;border-color:var(--b)}
.ft{text-align:center;padding:20px;color:var(--m);font-size:12px}
@media(max-width:768px){.ly{flex-direction:column}.sb{display:none}}"""

    revpar_vals = [d.get("revpar") or 0 for d in daily]
    adr_vals = [d.get("adr") or 0 for d in daily]

    return f'''<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>酒店 OTA 全面诊断报告</title><style>{style}</style></head>
<body>
<header class="hd"><div><h1>酒店 OTA 全面诊断报告</h1>
<p>{esc(hotel_name)} ｜ 周期：{PERIOD_START} 至 {PERIOD_END} ｜ 渠道：美团 ｜ 生成：{now}</p></div>
<div><button class="btn p" onclick="window.print()">导出报告</button></div></header>
<div class="ly">
<nav class="sb"><a href="#ov">总览</a><a href="#mod">模块得分</a><a href="#tr">经营趋势</a><a href="#pr">价格对比</a><a href="#hos">OTA健康</a><a href="#tk">整改任务</a><a href="#ms">缺失字段</a></nav>
<main>
<section id="ov" class="sec"><div class="sh"><h2>诊断总览</h2><span class="s {sc(final/100)}">{risk}</span></div>
<div class="sb2"><div class="kg">{kpi}</div><div class="ca"><b>封顶规则</b><ul>{caps_html}</ul></div></div></section>

<section id="mod" class="sec"><div class="sh"><h2>模块得分</h2></div><div class="sb2">{render_table(mr)}</div></section>

<section id="tr" class="sec"><div class="sh"><h2>经营趋势（日度）</h2></div>
<div class="sb2"><h3 style="margin-top:0">RevPAR & ADR 趋势</h3>{render_trend_chart(revpar_vals,adr_vals)}
<div class="lg"><span><i style="background:#2563eb"></i>RevPAR</span><span><i style="background:#168a4a"></i>ADR</span></div>
<h3>日度数据明细</h3>{render_table(tr)}</div></section>

<section id="pr" class="sec"><div class="sh"><h2>价格竞争力对比</h2><span class="s warn">数据日期: {op.get('business_date','')}</span></div>
<div class="sb2">{render_table(pr_rows)}</div></section>

<section id="hos" class="sec"><div class="sh"><h2>OTA 健康度</h2></div>
<div class="sb2">{render_table(hos_rows)}</div></section>

<section id="tk" class="sec"><div class="sh"><h2>整改任务</h2></div>
<div class="sb2">{render_table(tk)}</div></section>

<section id="ms" class="sec"><div class="sh"><h2>缺失字段</h2></div>
<div class="sb2">{render_table(ms)}</div></section>
</main></div>
<footer class="ft">S14 酒店OTA全面诊断报告 ｜ 测试环境 ｜ 数据源: hotel_pricing MySQL ｜ 计算公式: S14 runtime/calculator.py<br>
⚠️ 数据新鲜度: stale（最新业务日期 {op.get('business_date','未知')}），不得用于今日快报或实时调价</footer>
</body></html>'''

def main():
    conn = get_conn()
    try:
        hotel_name = "星锋电竞酒店（贵州大学花溪公园店）"
        
        # Fetch data from MySQL
        daily_records = fetch_daily_metrics(conn, hotel_name)
        op = fetch_operating_snapshot(conn, hotel_name)
        prices = fetch_price_data(conn, hotel_name)
        op_diag = fetch_operation_diagnosis(conn, hotel_name)
        
        # Field completeness
        available = sum(1 for x in [
            bool(daily_records), bool(op), bool(prices), bool(op_diag),
            op_diag.get("exposure"), op_diag.get("views"),
            op_diag.get("payment_conversion_rate"), op_diag.get("rating_total"),
        ] if x)
        field_comp = available / 9
        
        metrics = {
            "daily_records": daily_records,
            "operating": op,
            "prices": prices,
            "field_completeness": round(field_comp, 4),
        }
        
        # Score
        modules, caps = compute(metrics, op_diag)
        
        # Report
        html = generate_report(metrics, modules, caps, hotel_name, op_diag)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_HTML.write_text(html, encoding="utf-8")
        
        raw = sum(m.score for m in modules)
        final = raw
        for c in caps:
            if "C06" in c: final=min(final,70)
            elif "C04" in c: final=min(final,82)
            elif "C07" in c: final=min(final,80)
            elif "C01" in c: final=min(final,75)
        
        result = {
            "status": "partial" if caps else "ok",
            "skill_id": "s14-operation-diagnosis",
            "data_source": "hotel_pricing_mysql",
            "hotel_name": hotel_name,
            "hotel_id": HOTEL_ID,
            "platform": PLATFORM,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "data_business_date": op.get("business_date"),
            "freshness_status": "stale",
            "raw_score": round(raw,2),
            "final_score": round(final,2),
            "risk_level": rl(final),
            "field_completeness": field_comp,
            "module_scores": [{"module_id":m.module_id,"name":m.name,"weight":m.weight,"score":m.score,"confidence":m.confidence} for m in modules],
            "triggered_caps": caps,
            "report_url": REPORT_URL,
            "report_file_path": str(OUTPUT_HTML),
            "generated_at": datetime.now().isoformat(),
            "daily_records_count": len(daily_records),
            "price_records_count": len(prices),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
