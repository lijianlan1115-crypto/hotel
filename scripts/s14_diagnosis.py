#!/usr/bin/env python3
"""S14 diagnosis with MySQL data, multi-platform support. Usage: python3 script.py [meituan|fliggy]"""
from __future__ import annotations
import html, json, math, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import pymysql

# --- Auto-load /etc/hotel-ota-ai/hotel-ota.env ---------------------------------
# Bot 进程不会 source 这个 env 文件，导致 HOTEL_OTA_DB_DSN 缺失 → RuntimeError。
# 启动时自动读一次：setdefault 不覆盖进程内已设置的 env，便于测试时 export 覆盖。
_ENV_FILE = Path("/etc/hotel-ota-ai/hotel-ota.env")
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        _key = _key.strip()
        _value = _value.strip().strip('"').strip("'")
        os.environ.setdefault(_key, _value)
# -------------------------------------------------------------------------------

OUTPUT_DIR = Path("/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports")
OUTPUT_HTML = OUTPUT_DIR / "ota_diagnosis_report_demo.html"
REPORT_URL = "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html"
HOTEL_NAME = "星锋电竞酒店（贵州大学花溪公园店）"
PERIOD_START = "2026-06-01"
PERIOD_END = "2026-06-10"

PLATFORM = sys.argv[1] if len(sys.argv) > 1 else "meituan"
PLATFORM_CONFIG = {
    "meituan": {"name": "美团", "metric_item": "美团", "channel": "meituan"},
    "fliggy": {"name": "飞猪", "metric_item": "淘宝-飞猪", "channel": "feizhu"},
}
cfg = PLATFORM_CONFIG.get(PLATFORM, PLATFORM_CONFIG["meituan"])

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
def sc(r):
    if r<0.6: return "bad"
    if r<0.8: return "warn"
    return "good"
def sl(r):
    if r<0.6: return "严重短板"
    if r<0.8: return "需优化"
    return "正常"
def rl(s):
    if s<60: return "高风险"
    if s<80: return "中风险"
    return "低风险"

def get_conn():
    dsn = os.environ.get("HOTEL_OTA_DB_DSN","")
    if not dsn: raise RuntimeError("HOTEL_OTA_DB_DSN not set")
    p = urlparse(dsn)
    return pymysql.connect(host=p.hostname,port=p.port or 3306,user=p.username,
        password=p.password,database=p.path.lstrip("/"),charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor)

def fetch_daily_metrics(conn, metric_item: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT business_date, metric_name, metric_value
        FROM fact_daily_metrics
        WHERE hotel_name=%s AND metric_group IN ('渠道','总营业指标')
        AND metric_item IN (%s,'总营业指标')
        AND business_date BETWEEN %s AND %s
        ORDER BY business_date, metric_group, metric_item, metric_name
    """, (HOTEL_NAME, metric_item, PERIOD_START, PERIOD_END))
    rows = cur.fetchall()
    by_date: dict[str,dict] = {}
    for r in rows:
        d = str(r["business_date"])
        if d not in by_date: by_date[d] = {}
        name = str(r["metric_name"])
        val = to_float(r["metric_value"])
        by_date[d][name] = val
    records = []
    for d in sorted(by_date.keys()):
        m = by_date[d]
        occ_raw = m.get("出租率")
        occ = occ_raw/100 if occ_raw and occ_raw>1 else occ_raw
        revpar = m.get("RevPar") or m.get("revpar")
        if not revpar:
            adr = m.get("平均房价") or m.get("adr")
            if adr and occ: revpar = adr * occ
        records.append({
            "date": d,
            "room_revenue": m.get("房费") or m.get("room_fee"),
            "adr": m.get("平均房价") or m.get("adr"),
            "occupancy": occ,
            "room_nights": m.get("间夜数") or m.get("过夜房") or m.get("room_nights"),
            "revpar": revpar,
            "available_rooms": 31,
        })
    return records

def fetch_operating_snapshot(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM operating_snapshot WHERE hotel_name=%s ORDER BY business_date DESC LIMIT 1", (HOTEL_NAME,))
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

def fetch_price_data(conn, channel: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""SELECT * FROM price_data WHERE hotel_name=%s AND channel=%s
        AND business_date=(SELECT MAX(business_date) FROM price_data WHERE hotel_name=%s AND channel=%s)""",
        (HOTEL_NAME, channel, HOTEL_NAME, channel))
    return cur.fetchall()

def fetch_operation_diagnosis(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM operation_diagnosis WHERE hotel_name=%s ORDER BY business_date DESC LIMIT 1", (HOTEL_NAME,))
    return cur.fetchone() or {}

# ========== SCORING ==========
MODULES = {
    "M01":("经营结果与收益锚点",20),"M02":("流量曝光与竞争圈",15),
    "M03":("转化下单与路径断点",15),"M04":("价格收益与房态库存",15),
    "M05":("推广效率与ROI",10),"M06":("页面展示与入口基础",10),
    "M07":("口碑信任与服务响应",8),"M08":("执行复盘与数据完整度",7),
}

RULES = [
    ("V4-001","M01","订单竞争力",4),("V4-002","M01","收入环比",4),
    ("V4-003","M01","RevPAR趋势",4),("V4-004","M01","ADR竞争力",4),
    ("V4-005","M01","流失控制",4),("V4-006","M02","OTA渠道占比",4),
    ("V4-007","M02","曝光量趋势",4),("V4-008","M02","浏览量趋势",4),
    ("V4-009","M02","竞争圈排名",3),("V4-012","M03","浏览-下单转化",4),
    ("V4-013","M03","下单-支付转化",4),("V4-014","M03","支付成功率",4),
    ("V4-015","M03","流失挽回率",3),("V4-017","M04","房型健康度",5),
    ("V4-018","M04","价格竞争力",5),("V4-019","M04","库存利用率",5),
    ("V4-023","M05","推广ROI",4),("V4-024","M05","推广曝光量",2),
    ("V4-025","M05","推广点击率",2),("V4-026","M05","CPC效率",2),
    ("V4-028","M06","图片质量",3),("V4-029","M06","视频状态",2),
    ("V4-030","M06","房型卖点",2),("V4-031","M06","入口标签",3),
    ("V4-033","M07","平台评分",3),("V4-034","M07","差评率",2),
    ("V4-035","M07","回复率",3),("V4-038","M08","字段完整度",3),
    ("V4-039","M08","整改动作",2),("V4-040","M08","复盘质量",2),
]

def score_ratio(value, target, points):
    if value is None or target in (None,0): return points*0.5
    return points*clamp((value/target)/1.2)

def compute(daily, op, prices, op_diag, field_comp, is_fliggy=False) -> tuple[list, list]:
    latest = daily[-1] if daily else {}
    recent_revpar = latest.get("revpar") or op.get("revpar") or 0
    recent_adr = latest.get("adr") or op.get("adr") or 0
    recent_occ = latest.get("occupancy") or op.get("occupancy_rate") or 0
    revpar_trend = [d.get("revpar") or 0 for d in daily[-3:]] if len(daily)>=3 else [recent_revpar]
    revpar_avg3 = sum(revpar_trend)/max(1,len(revpar_trend))
    revenues = [d.get("room_revenue") or 0 for d in daily]
    revenue_mom = (revenues[-1]-revenues[-2])/revenues[-2] if len(revenues)>=2 and revenues[-2] else None

    above_comp = sum(1 for p in prices if to_float(p.get("current_price")) and to_float(p.get("competitor_price")) and to_float(p["current_price"])>to_float(p["competitor_price"]))
    total_rt = len(prices) or 1

    rs: dict[str,tuple[float,str]] = {}
    for rid,mid,name,pts in RULES:
        s=pts*0.65; r=f"{name}: 默认"
        if rid=="V4-001":
            orders=op.get("orders_today") or 0
            s=pts*clamp(orders/15); r=f"{name}: 订单 {orders:.0f}单"
        elif rid=="V4-002":
            s=pts*(0.95 if revenue_mom and revenue_mom>0 else (0.7 if revenue_mom and revenue_mom>-0.1 else 0.45))
            r=f"{name}: 收入环比 {pct(revenue_mom)}"
        elif rid=="V4-003":
            s=score_ratio(recent_revpar,revpar_avg3,pts)
            r=f"{name}: RevPAR {recent_revpar:.2f} vs 近3日 {revpar_avg3:.2f}"
        elif rid=="V4-004":
            s=pts*(0.85 if recent_adr>130 else (0.7 if recent_adr>100 else 0.5))
            r=f"{name}: ADR {recent_adr:.2f}"
        elif rid=="V4-005":
            s=pts*0.55; r=f"{name}: 流失待补采"
        elif rid=="V4-006":
            s=pts*(0.5 if is_fliggy else 0.75)
            r=f"{name}: {'飞猪渠道占比较低' if is_fliggy else '美团为主~80%'}"
        elif rid in ("V4-007","V4-008"):
            exp=to_float(op_diag.get("exposure"))
            s=pts*(0.8 if exp else 0.5)
            r=f"{name}: 曝光{'已采集' if exp else '待补采'}"
        elif rid=="V4-009":
            pr=to_float(op_diag.get("peer_rank"))
            s=pts*(0.95 if pr and pr<=5 else (0.8 if pr and pr<=15 else (0.6 if pr else 0.5)))
            r=f"{name}: 排名 {'第'+str(int(pr)) if pr else '待补采'}"
        elif rid in ("V4-012","V4-013","V4-014","V4-015"):
            pcr=to_float(op_diag.get("payment_conversion_rate"))
            s=pts*(0.85 if pcr and pcr>0.1 else (0.65 if pcr else 0.45))
            r=f"{name}: 支付转化 {pct(pcr) if pcr else '待补采'}"
        elif rid=="V4-017":
            weak=sum(1 for p in prices if to_float(p.get("current_price")) and to_float(p.get("competitor_price")) and to_float(p["current_price"])<to_float(p["competitor_price"])*0.9)
            s=pts*(0.55 if weak>1 else (0.75 if weak>0 else 0.85))
            r=f"{name}: 低于竞对90% {weak}个"
        elif rid=="V4-018":
            s=pts*(0.8 if above_comp/total_rt>0.3 else (0.6 if above_comp>0 else 0.45))
            r=f"{name}: 高于竞对 {above_comp}/{total_rt}"
        elif rid=="V4-019":
            s=pts*clamp(recent_occ/0.85) if recent_occ else pts*0.5
            r=f"{name}: 出租率 {pct(recent_occ)}"
        elif rid in ("V4-023","V4-024","V4-025","V4-026"):
            s=pts*0.45; r=f"{name}: 推广待补采"
        elif rid in ("V4-028","V4-029","V4-030","V4-031"):
            hos=to_float(op_diag.get("hos_score"),3.0)
            s=pts*clamp(hos/5); r=f"{name}: HOS {hos:.0f}"
        elif rid in ("V4-033","V4-034","V4-035"):
            rt=to_float(op_diag.get("rating_total"),4.0)
            br=to_float(op_diag.get("bad_review_rate"),0.05)
            s=pts*clamp((rt/5)-(br*2)); r=f"{name}: 评分{rt:.1f} 差评{pct(br)}"
        elif rid=="V4-038":
            s=pts*field_comp; r=f"{name}: 字段完整度 {pct(field_comp)}"
        elif rid in ("V4-039","V4-040"):
            s=pts*0.55; r=f"{name}: 待补充"
        rs[rid]=(s,r)

    modules=[]
    for mid,(mname,wt) in MODULES.items():
        mrs=[(rid,name,pts) for rid,mid2,name,pts in RULES if mid2==mid]
        ss=sum(rs[rid][0] for rid,_,_ in mrs)
        ss=min(ss,float(wt))
        reasons=[f"{name}: {rs[rid][1]}" for rid,name,_ in mrs[:3]]
        conf="high" if field_comp>=0.8 else ("medium" if field_comp>=0.55 else "low")
        modules.append({"module_id":mid,"name":mname,"weight":float(wt),"score":round(ss,2),"reasons":reasons,"confidence":conf})

    caps=[]
    if field_comp<0.7: caps.append("C06 数据可信度封顶: 字段缺失>30%, 总分≤70")
    if any(m["module_id"]=="M03" and m["score"]/m["weight"]<0.6 for m in modules): caps.append("C04 转化封顶: M03<60%")
    if any(m["module_id"]=="M01" and m["score"]/m["weight"]<0.6 for m in modules): caps.append("C07 基础项封顶: M01<60%")
    raw=sum(m["score"] for m in modules)
    if raw>=85 and recent_revpar<120: caps.append("C01 收益封顶: RevPAR<120, 总分≤75")
    return modules,caps

# ========== REPORT ==========
def render_table(rows):
    if not rows: return ""
    h="".join(f"<th>{esc(x)}</th>" for x in rows[0])
    b="".join("<tr>"+"".join(f"<td>{x}</td>" for x in r)+"</tr>" for r in rows[1:])
    return f"<table class='dt'><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"

def generate(metrics,modules,caps,is_fliggy):
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw=sum(m["score"] for m in modules)
    final=raw
    for c in caps:
        if "C06" in c: final=min(final,70)
        elif "C04" in c: final=min(final,82)
        elif "C07" in c: final=min(final,80)
        elif "C01" in c: final=min(final,75)
    risk=rl(final)
    daily=metrics["daily"]; op=metrics["op"]; prices=metrics["prices"]
    fc=metrics["field_comp"]; odiag=metrics["op_diag"]

    kpi=f'''<div class="kpi"><label>总分</label><strong class="num">{final:.0f}/100</strong><span>原始 {raw:.1f}</span></div>
<div class="kpi"><label>风险</label><strong class="num">{risk}</strong><span>字段完整度 {fc*100:.0f}%</span></div>
<div class="kpi"><label>{cfg['name']}经营</label><strong>出租 {pct(next((d.get('occupancy') for d in reversed(daily) if d.get('occupancy')),None))}</strong><span>ADR ¥{next((d.get('adr') for d in reversed(daily) if d.get('adr')),0):.0f} | 间夜 {next((d.get('room_nights') for d in reversed(daily) if d.get('room_nights')),0):.0f}</span></div>
<div class="kpi"><label>数据日期</label><strong class="num">{op.get('business_date','-')}</strong><span>hotel_pricing MySQL</span></div>'''

    ch="".join(f"<li>{esc(c)}</li>" for c in caps) or "<li>未触发封顶</li>"

    mr=[["模块","得分","得分率","状态","核心依据"]]
    for m in modules:
        rate=m["score"]/m["weight"] if m["weight"] else 0
        mr.append([f'{m["module_id"]} {esc(m["name"])}',f'{m["score"]:.1f}/{m["weight"]:.0f}',f'{rate*100:.0f}%',
            f'<span class="s {sc(rate)}">{sl(rate)}</span>',"<br>".join(esc(r) for r in m["reasons"])])

    tr=[["日期","ADR","出租率","RevPAR","房费收入","间夜"]]
    for d in daily:
        tr.append([d["date"],f'{d.get("adr",0):.2f}',pct(d.get("occupancy")),f'{d.get("revpar",0):.2f}',
            money(d.get("room_revenue")),f'{d.get("room_nights",0):.0f}'])

    pr=[["房型","渠道","当前价","竞对价","价差","判断"]]
    for p in prices[:12]:
        cp=to_float(p.get("current_price")); comp=to_float(p.get("competitor_price"))
        gap=(cp-comp)/comp*100 if cp and comp else None
        cls=sc(0.85) if gap and gap>0 else sc(0.5)
        pr.append([esc(p.get("room_type_id","")),esc(p.get("channel","")),
            f"¥{cp:.0f}" if cp else "-",f"¥{comp:.0f}" if comp else "-",
            f"{gap:+.1f}%" if gap is not None else "-",
            f'<span class="s {cls}">{"高于" if gap and gap>0 else "低于"}竞对</span>'])

    # Channel-specific insights
    if is_fliggy:
        insight_title = "飞猪渠道专项分析"
        insight = f"""<p>飞猪渠道特征：</p><ul>
<li>仅覆盖 <b>至臻·电竞大床房</b> 1个房型（共31间房中的1间）</li>
<li>日间夜量 1-8 间，渠道间夜占比极低</li>
<li>价格略低于竞对 ~1%，缺乏独立定价策略</li>
<li>无独立推广投放数据</li>
<li>订单来自飞猪信用住直连</li>
</ul>"""
    else:
        insight_title = "美团渠道专项分析"
        insight = f"""<p>美团渠道特征：</p><ul>
<li>覆盖全部 7+ 房型，主渠道间夜占比~80%</li>
<li>出租率 67.7%，ADR ¥130，RevPAR ¥88</li>
<li>全面略低于竞对 ~1%，无差异化定价</li>
<li>推广参谋数据未入库（曝光/点击/CPC缺失）</li>
</ul>"""

    tk=[["优先级","负责人","整改动作","周期"]]
    if is_fliggy:
        tk.append(["P0","OTA运营","扩充飞猪上架房型至核心5款","7天"])
        tk.append(["P0","OTA运营","配置飞猪独立定价策略","3天"])
        tk.append(["P1","收益经理","接入飞猪经营趋势和推广数据","7天"])
    else:
        tk.append(["P0","OTA运营","补采美团推广参谋曝光/点击/CPC","3天"])
        tk.append(["P0","OTA运营","差异化管理各房型竞对价差","7天"])
        tk.append(["P1","收益经理","分析低出租率房型原因","7天"])
    tk.append(["P1","门店店长","补拍首图/电竞细节/完善标签","14天"])
    tk.append(["P2","运营负责人","建立日报复报机制","14天"])

    ms=[["缺失字段","影响","建议"]]
    missing=[("推广参谋数据(曝光/点击/CPC)","M05","从OTA后台导出推广报表"),
             ("流量转化漏斗(浏览-下单-支付)","M03","接入商家版或API"),
             ("竞对实时价库","M02/M04","每日采集核心竞对价格"),
             ("房型图片/视频质量","M06","补拍首图及电竞设备细节")]
    if is_fliggy:
        missing.insert(0,("飞猪多渠道房型覆盖","M01/M02/M04","上架至臻双床/开黑双床/独享单人等高需求房型"))
    for f,m,sug in missing: ms.append([f,m,sug])

    style="""*{box-sizing:border-box}:root{--bg:#f6f7f9;--p:#fff;--i:#1d2430;--m:#667085;--l:#d9dee8;--b:#2563eb;--g:#168a4a;--a:#b7791f;--r:#c2413a}
body{margin:0;background:var(--bg);color:var(--i);font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
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
.btn{padding:8px 16px;border-radius:6px;border:1px solid var(--l);background:var(--p);cursor:pointer;font-size:13px}
.btn.p{background:var(--b);color:#fff;border-color:var(--b)}
.ft{text-align:center;padding:20px;color:var(--m);font-size:12px}
@media(max-width:768px){.ly{flex-direction:column}.sb{display:none}}"""

    return f'''<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>酒店 OTA 全面诊断报告 - {cfg["name"]}</title><style>{style}</style></head>
<body>
<header class="hd"><div><h1>酒店 OTA 全面诊断报告 — {cfg["name"]}</h1>
<p>{esc(HOTEL_NAME)} | {PERIOD_START}~{PERIOD_END} | 生成: {now}</p></div>
<div><button class="btn p" onclick="window.print()">导出报告</button></div></header>
<div class="ly">
<nav class="sb"><a href="#ov">总览</a><a href="#mod">模块得分</a><a href="#tr">经营趋势</a><a href="#pr">价格对比</a><a href="#in">渠道分析</a><a href="#tk">整改任务</a><a href="#ms">缺失字段</a></nav>
<main>
<section id="ov" class="sec"><div class="sh"><h2>诊断总览</h2><span class="s {sc(final/100)}">{risk}</span></div>
<div class="sb2"><div class="kg">{kpi}</div><div class="ca"><b>封顶规则</b><ul>{ch}</ul></div></div></section>
<section id="mod" class="sec"><div class="sh"><h2>模块得分</h2></div><div class="sb2">{render_table(mr)}</div></section>
<section id="tr" class="sec"><div class="sh"><h2>{cfg["name"]}经营趋势（日度）</h2></div>
<div class="sb2">{render_table(tr)}</div></section>
<section id="pr" class="sec"><div class="sh"><h2>{cfg["name"]}价格竞争力</h2><span class="s warn">数据: {op.get('business_date','')}</span></div>
<div class="sb2">{render_table(pr)}</div></section>
<section id="in" class="sec"><div class="sh"><h2>{insight_title}</h2></div>
<div class="sb2">{insight}</div></section>
<section id="tk" class="sec"><div class="sh"><h2>整改任务</h2></div>
<div class="sb2">{render_table(tk)}</div></section>
<section id="ms" class="sec"><div class="sh"><h2>缺失字段</h2></div>
<div class="sb2">{render_table(ms)}</div></section>
</main></div>
<footer class="ft">S14 OTA诊断 | 测试环境 | hotel_pricing MySQL | 数据日期: {op.get('business_date','-')}</footer>
</body></html>'''

def main():
    conn = get_conn()
    try:
        is_fliggy = PLATFORM == "fliggy"
        daily = fetch_daily_metrics(conn, cfg["metric_item"])
        op = fetch_operating_snapshot(conn)
        prices = fetch_price_data(conn, cfg["channel"])
        op_diag = fetch_operation_diagnosis(conn)

        available = sum(1 for x in [bool(daily),bool(op),bool(prices),bool(op_diag),
            op_diag.get("exposure"),op_diag.get("views"),
            op_diag.get("payment_conversion_rate"),op_diag.get("rating_total")] if x)
        fc = min(available/9, 1.0)

        modules, caps = compute(daily, op, prices, op_diag, round(fc,4), is_fliggy)
        html = generate({"daily":daily,"op":op,"prices":prices,"field_comp":round(fc,4),"op_diag":op_diag}, modules, caps, is_fliggy)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_HTML.write_text(html, encoding="utf-8")

        raw=sum(m["score"] for m in modules); final=raw
        for c in caps:
            if "C06" in c: final=min(final,70)
            elif "C04" in c: final=min(final,82)
            elif "C07" in c: final=min(final,80)
            elif "C01" in c: final=min(final,75)

        result={
            "status":"partial" if caps else "ok","skill_id":"s14-operation-diagnosis",
            "data_source":"hotel_pricing_mysql","hotel_name":HOTEL_NAME,
            "platform":PLATFORM,"platform_name":cfg["name"],
            "period_start":PERIOD_START,"period_end":PERIOD_END,
            "raw_score":round(raw,2),"final_score":round(final,2),
            "risk_level":rl(final),"field_completeness":round(fc,4),
            "module_scores":modules,"triggered_caps":caps,
            "report_url":REPORT_URL,"generated_at":datetime.now().isoformat(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
