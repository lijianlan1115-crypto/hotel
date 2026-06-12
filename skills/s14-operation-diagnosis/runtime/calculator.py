"""S14 V4 formulas: 41 sub-rules + C01-C07 caps."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

MODULE_DEFS={"M01":("经营结果与收益锚点",20),"M02":("流量曝光与竞争圈",15),"M03":("转化下单与路径断点",15),"M04":("价格收益与房态库存",15),"M05":("推广效率与 ROI",10),"M06":("页面展示与入口基础",10),"M07":("口碑信任与服务响应",8),"M08":("执行复盘与数据完整度",7)}
RULE_POINTS={"M01":[("V4-001订单结果",4),("V4-002收入结果",4),("V4-003RevPAR收益质量",5),("V4-004ADR价格质量",3),("V4-005流失损失",2),("V4-006客源结构收益",2)],"M02":[("V4-007曝光竞争圈倍数",4),("V4-008浏览竞争圈倍数",3),("V4-009广告/非广告曝光结构",3),("V4-010入口覆盖",3),("V4-011流量趋势",2)],"M03":[("V4-012曝光-浏览转化",4),("V4-013浏览-支付转化",5),("V4-014支付订单能力",3),("V4-015流失订单",2),("V4-016订单结构匹配",1)],"M04":[("V4-017库存销售速度",4),("V4-018房型RevPAR分层",3),("V4-019价格带覆盖",3),("V4-020活动价一致性",2),("V4-021预留房/房态",2),("V4-022竞对价格承受力",1)],"M05":[("V4-023推广ROI",3),("V4-024推广订单产出",2),("V4-025推广点击效率",2),("V4-026推广曝光有效性",2),("V4-027推广趋势稳定性",1)],"M06":[("V4-028信息分与名称",2),("V4-029权益与服务配置",2),("V4-030图片视频亮点",2),("V4-031房型表达",2),("V4-032筛选/标签/入口",2)],"M07":[("V4-033点评分与大众点评",3),("V4-034点评数量与新增",1),("V4-035回复率与时效",1),("V4-036差评类型",2),("V4-037好评卖点反哺",1)],"M08":[("V4-038数据完整度",2),("V4-039动作完成率",2),("V4-040整改前后对比",2),("V4-041异常复盘",1)]}
MISS=(None,"","null","None","--","-",[],{})
@dataclass
class ScoreResult: module_id:str; name:str; score:float; weight:float; confidence:str; reasons:list[str]
def x(v,d=0):
    if v in MISS:return d
    if isinstance(v,str):
        t=v.strip().replace(',','')
        if t.endswith('%'):
            try:return float(t[:-1])/100
            except ValueError:return d
        try:return float(t)
        except ValueError:return d
    try:return float(v)
    except Exception:return d
def n(m,k,d=0):return x(m.get(k,d),d)
def a(m,ks,d=0):
    for k in ks:
        if m.get(k) not in MISS:return x(m[k],d)
    return d
def c(v):return max(0,min(1,v))
def ratio(v,t,up=True):return 0 if t<=0 else c(v/t if up else t/max(v,1e-6))
def peer(v,p):return .6 if p<=0 else c(v/p)
def tr(v):return 1 if v>=.05 else .25 if v<=-.10 else c(.25+(v+.10)/.15*.75)
def bs(v,d=.6):
    if v in MISS:return d
    if isinstance(v,str):
        s=v.strip().lower()
        if s in {'1','yes','true','是','正常','已开通','complete','good'}:return 1
        if s in {'partial','average','可优化','部分'}:return .65
        if s in {'0','no','false','否','缺失','未开通','poor','missing','待改善'}:return .25
    return 1 if v else .25
def es(v,mp,d=.6):return mp.get(str(v or 'unknown'),d)
def item(rule,pts,f):
    s=round(pts*c(f),2);return s,f"{rule}={s:.2f}/{pts:g}"
def score_parts(parts):
    ss=[item(*p) for p in parts];return sum(s for s,_ in ss),[r for _,r in ss]

def calculate_module_score(module_id:str,metrics:dict[str,Any])->ScoreResult:
    score,reasons=globals()[module_id.lower()](metrics);name,w=MODULE_DEFS[module_id];comp=n(metrics,'field_completeness',1);conf='high' if comp>=.8 else 'medium' if comp>=.55 else 'low';return ScoreResult(module_id,name,round(min(max(score,0),w),2),w,conf,reasons)
def calculate_all_modules(metrics):return [calculate_module_score(mid,metrics) for mid in MODULE_DEFS]

def m01(m):
    orders=a(m,['paid_orders','payment_orders','orders','order_count']);po=a(m,['peer_paid_orders','peer_orders','peer_avg_paid_orders']);rev=a(m,['room_revenue','store_revenue','sales_amount','revenue']);revpar=n(m,'revpar');adr=n(m,'adr');occ=n(m,'occupancy');padr=a(m,['peer_adr','competitor_adr','market_adr']);prev=a(m,['peer_revpar','competitor_revpar','market_revpar']);r3=a(m,['revpar_3m_avg','last_3m_revpar_avg']);lostbase=max(rev*.08,adr*max(n(m,'lost_orders'),1),1);ota=a(m,['ota_share','ota_occupancy_share','ota_room_night_share'],.5);src=.55 if ota>.7 and a(m,['ota_adr','ota_avg_price'],adr)<a(m,['direct_adr','member_adr','walkin_adr'],adr)*.9 else .75 if ota>.6 else 1
    s,r=score_parts([('V4-001订单结果',4,peer(orders,po)*.65+tr(a(m,['order_mom','paid_orders_mom','orders_mom']))*.35),('V4-002收入结果',4,ratio(rev,a(m,['revenue_target','room_revenue_target'],rev or 1))*.55+tr(a(m,['revenue_mom','room_revenue_mom']))*.45),('V4-003RevPAR收益质量',5,max(peer(revpar,prev),peer(revpar,r3))*.75+ratio(occ,.85)*.25),('V4-004ADR价格质量',3,peer(adr,padr)*.75+(.6 if occ>.9 and padr and adr<padr*.9 else 1)*.25),('V4-005流失损失',2,ratio(n(m,'lost_amount'),lostbase,False)),('V4-006客源结构收益',2,src)]);return s,r

def m02(m):
    ad=a(m,['ad_exposure','promo_exposure','paid_exposure']);free=a(m,['organic_exposure','non_ad_exposure','free_exposure']);share=ad/(ad+free) if ad+free else a(m,['ad_exposure_share','paid_exposure_share'],.35);entry=a(m,['entry_coverage_rate','poi_tag_coverage','tag_coverage','entry_tag_score'],-1);entry=(bs(m.get('business_area_tag_status'))+bs(m.get('poi_status'))+bs(m.get('facility_tag_status'))+bs(m.get('entry_tag_quality')))/4 if entry<0 else entry;adstruct=1 if share<=.55 else .75 if a(m,['paid_orders','payment_orders','orders'])>0 else .45
    return score_parts([('V4-007曝光竞争圈倍数',4,peer(n(m,'exposure'),a(m,['peer_exposure','peer_avg_exposure','competitor_exposure']))),('V4-008浏览竞争圈倍数',3,peer(n(m,'views'),a(m,['peer_views','peer_avg_views','competitor_views']))),('V4-009广告/非广告曝光结构',3,adstruct),('V4-010入口覆盖',3,entry),('V4-011流量趋势',2,(tr(a(m,['exposure_7d_trend','exposure_mom']))+tr(a(m,['views_7d_trend','views_mom'])))/2)])

def m03(m):
    exp=n(m,'exposure');views=n(m,'views');e2v=a(m,['exposure_to_view_rate','booking_conversion_rate'],views/exp if exp else 0);pay=n(m,'payment_conversion_rate');orders=a(m,['paid_orders','payment_orders','orders']);lost=n(m,'lost_orders');struct=a(m,['order_structure_match_rate','customer_structure_match_rate'],-1);struct=bs(m.get('order_structure_status')) if struct<0 else struct
    return score_parts([('V4-012曝光-浏览转化',4,peer(e2v,a(m,['peer_exposure_to_view_rate','peer_booking_conversion_rate']))),('V4-013浏览-支付转化',5,peer(pay,a(m,['peer_payment_conversion_rate','peer_view_to_pay_rate']))),('V4-014支付订单能力',3,peer(orders,a(m,['peer_paid_orders','peer_orders','peer_avg_paid_orders']))),('V4-015流失订单',2,ratio(lost,max(orders*.15,3,n(m,'lost_amount')/max(n(m,'adr',1),1)),False)),('V4-016订单结构匹配',1,struct)])

def m04(m):
    adr=n(m,'adr');padr=a(m,['peer_adr','competitor_adr','market_adr'],adr);sold=a(m,['sold_room_nights','sold_rooms']);avail=a(m,['available_room_nights','available_rooms','total_room_nights']);remain=a(m,['remaining_room_nights','remaining_rooms'],max(avail-sold,0));speed=a(m,['sales_speed','sell_through_rate'],sold/avail if avail else 0);inv=.45 if speed>.85 and adr<padr*.9 else .7 if speed>.75 and adr<padr else ratio(speed,.75)*.55+ratio(remain,max(avail*.15,1),False)*.45;reserve=ratio(a(m,['reserved_room_rate','reserved_room_ratio','reserve_room_rate'],.3),.3)*.45+a(m,['room_status_health_rate','inventory_health_rate'],.7)*.55;power=a(m,['competitor_price_power','price_tolerance_score'],-1);power=peer(adr,padr) if power<0 and padr else (.6 if power<0 else power)
    return score_parts([('V4-017库存销售速度',4,inv),('V4-018房型RevPAR分层',3,a(m,['room_type_health_rate','room_type_revpar_health','efficient_room_type_rate'],.6)),('V4-019价格带覆盖',3,a(m,['price_band_coverage','price_completeness'],.6)),('V4-020活动价一致性',2,a(m,['activity_price_consistency','rate_parity_score','price_consistency'],.7)),('V4-021预留房/房态',2,reserve),('V4-022竞对价格承受力',1,power)])

def m05(m):
    amount=a(m,['promo_amount','promo_booking_amount','ad_booking_amount']);cost=n(m,'promo_cost');roi=n(m,'promo_roi',amount/cost if cost else 0);clicks=a(m,['promo_clicks','ad_clicks','clicks']);exp=a(m,['promo_exposure','ad_exposure','paid_exposure']);ctr=a(m,['promo_ctr','ad_ctr','click_rate'],clicks/exp if exp else 0);cpc=a(m,['promo_cpc','ad_cpc','click_price'],cost/clicks if clicks else 0)
    return score_parts([('V4-023推广ROI',3,ratio(roi,a(m,['promo_roi_target','roi_target'],5))),('V4-024推广订单产出',2,ratio(a(m,['promo_orders','promo_booking_orders','ad_orders']),a(m,['promo_order_target'],max(cost/max(n(m,'adr',150),1),1)))),('V4-025推广点击效率',2,ratio(ctr,.03)*.55+ratio(cpc,a(m,['promo_cpc_target','cpc_target'],2.5),False)*.45),('V4-026推广曝光有效性',2,.25 if cost>0 and exp<=0 else ratio(exp,a(m,['promo_exposure_target'],3000))),('V4-027推广趋势稳定性',1,(tr(a(m,['promo_roi_7d_trend','roi_7d_trend']))+tr(a(m,['promo_order_7d_trend','promo_orders_7d_trend'])))/2)])

def m06(m):
    info=ratio(a(m,['hotel_info_score','meituan_info_score','info_score'],80),100)*.6+bs(m.get('hotel_name_keyword_status') or m.get('hotel_name_status'))*.4;rights=a(m,['benefit_coverage_rate','rights_coverage_rate'],-1);rights=rights if rights>=0 else (bs(m.get('rights_center_status'))+bs(m.get('invoice_status'))+bs(m.get('business_travel_status'))+bs(m.get('public_benefit_traffic_status')))/4;media=(es(m.get('image_quality_rating'),{'good':1,'average':.65,'poor':.25,'unknown':.6})+es(m.get('video_status'),{'complete':1,'partial':.65,'missing':.25,'unknown':.6})+bs(m.get('highlight_status')))/3;room=(bs(m.get('room_name_status'))+bs(m.get('room_description_status'))+es(m.get('room_selling_point_status'),{'complete':1,'partial':.65,'poor':.25,'unknown':.6}))/3;entry=a(m,['entry_tag_score','entry_coverage_rate','facility_tag_coverage'],-1);entry=es(m.get('entry_tag_quality'),{'complete':1,'partial':.65,'poor':.25,'unknown':.6}) if entry<0 else entry
    return score_parts([('V4-028信息分与名称',2,info),('V4-029权益与服务配置',2,rights),('V4-030图片视频亮点',2,media),('V4-031房型表达',2,room),('V4-032筛选/标签/入口',2,entry)])

def m07(m):
    rating=n(m,'rating_total',4);reviews=a(m,['review_count','reviews','rating_count']);reply=a(m,['review_reply_rate','reply_rate'],1-n(m,'unreplied_reviews')/max(reviews,1));bad=n(m,'bad_review_rate',.08)
    return score_parts([('V4-033点评分与大众点评',3,peer(rating,a(m,['peer_rating_total','peer_rating','competitor_rating'],4.6))*.7+ratio(a(m,['dianping_rating','dp_rating'],rating),4.8)*.3),('V4-034点评数量与新增',1,ratio(reviews,200)*.6+ratio(a(m,['new_review_count','new_reviews_30d']),10)*.4),('V4-035回复率与时效',1,ratio(reply,.98)*.6+ratio(a(m,['bad_review_reply_rate','negative_reply_rate'],reply),1)*.4),('V4-036差评类型',2,a(m,['bad_review_tag_score','negative_review_text_score'],ratio(bad,.03,False))),('V4-037好评卖点反哺',1,a(m,['good_keyword_usage_rate','review_keyword_to_page_rate'],bs(m.get('good_review_keywords_used'))))])

def m08(m):
    done=a(m,['completed_actions','completed_action_count']);pending=a(m,['pending_actions','pending_action_count']);action=a(m,['action_completion_rate','p0_p1_action_completion_rate'],done/(done+pending) if done+pending else .35);before=a(m,['before_after_compare_ready','remediation_compare_ready'],1 if m.get('before_metrics') and m.get('after_metrics') else .35);review=a(m,['anomaly_review_rate','exception_review_rate'],1 if m.get('review_reason') or m.get('anomaly_reason') else .35)
    return score_parts([('V4-038数据完整度',2,n(m,'field_completeness',.5)),('V4-039动作完成率',2,action),('V4-040整改前后对比',2,before),('V4-041异常复盘',1,review)])

def module_rate(scores,mid):
    for x0 in scores:
        if (x0.get('module_id') if isinstance(x0,dict) else x0.module_id)==mid:return float(x0.get('score',0) if isinstance(x0,dict) else x0.score)/max(float(x0.get('weight',MODULE_DEFS[mid][1]) if isinstance(x0,dict) else x0.weight),1e-6)
    return 0
def cap_module(scores,mid,mx,why):
    lim=round(MODULE_DEFS[mid][1]*mx,2)
    for x0 in scores:
        if (x0.get('module_id') if isinstance(x0,dict) else x0.module_id)!=mid:continue
        if isinstance(x0,dict) and float(x0.get('score',0))>lim:x0['score']=lim;x0.setdefault('reasons',[]).append(why)
        elif not isinstance(x0,dict) and x0.score>lim:x0.score=lim;x0.reasons.append(why)

def apply_cap_rules(module_scores,metrics):
    caps=[];revpar=n(metrics,'revpar');rev3=a(metrics,['revpar_3m_avg','last_3m_revpar_avg']);prev=a(metrics,['peer_revpar','competitor_revpar','market_revpar'])
    if (rev3 and revpar<rev3*.8) or (prev and revpar<prev*.8):caps.append('C01 收益封顶：RevPAR低于近3月均值或竞争圈均值20%以上，总分最高75。')
    if a(metrics,['revenue_decline_months','room_revenue_decline_months'])>=2 and not metrics.get('season_or_market_explained'):caps.append('C02 收入封顶：门店收入连续2个月下降且无法由季节/商圈解释，总分最高78。')
    orders=a(metrics,['paid_orders','payment_orders','orders']);porders=a(metrics,['peer_paid_orders','peer_orders','peer_avg_paid_orders']);pay=n(metrics,'payment_conversion_rate');ppay=a(metrics,['peer_payment_conversion_rate','peer_view_to_pay_rate'])
    if porders and ppay and orders<porders and pay<ppay and a(metrics,['orders_low_days','paid_orders_below_peer_days'],2)>=2:caps.append('C03 订单封顶：支付订单连续多日低于竞争圈且浏览-支付转化低于竞争圈，总分最高72。')
    if a(metrics,['peer_exposure','peer_avg_exposure','competitor_exposure']) and ppay and n(metrics,'exposure')>a(metrics,['peer_exposure','peer_avg_exposure','competitor_exposure']) and pay<ppay and a(metrics,['conversion_low_days','payment_conversion_below_peer_days'],2)>=2:cap_module(module_scores,'M02',.8,'C04：流量模块最高80%。');caps.append('C04 转化封顶：曝光高于竞争圈但浏览-支付转化连续低于竞争圈，流量模块最高80%，总分最高82。')
    cost=n(metrics,'promo_cost');amount=a(metrics,['promo_amount','promo_booking_amount','ad_booking_amount']);roi=n(metrics,'promo_roi',amount/cost if cost else 0)
    if cost>0 and (roi<a(metrics,['promo_roi_target','roi_target'],5) or amount<cost):cap_module(module_scores,'M05',.5,'C05：推广模块最高50%。');caps.append('C05 推广封顶：推广花费持续发生但ROI低于目标或预订金额无法覆盖成本，推广模块最高50%。')
    if n(metrics,'field_completeness',1)<.7:caps.append('C06 数据可信度封顶：关键经营字段缺失超过30%，总分标记暂估且最高70。')
    if (module_rate(module_scores,'M06')>=.8 or module_rate(module_scores,'M07')>=.8) and (module_rate(module_scores,'M01')<.6 or module_rate(module_scores,'M03')<.6):caps.append('C07 基础项封顶：基础配置高分但经营结果/转化核心模块低于60%，总分最高80。')
    total=sum(float(x0.get('score',0) if isinstance(x0,dict) else x0.score) for x0 in module_scores)
    for cid,lim in [('C01',75),('C02',78),('C03',72),('C04',82),('C06',70),('C07',80)]:
        if any(s.startswith(cid) for s in caps):total=min(total,lim)
    if not metrics.get('available_room_nights'):total=min(total,85);caps.append('数据补采提示：缺 available_room_nights 且无法推导，可售间夜相关判断偏弱。')
    return round(total,2),caps

def evaluate_remediation_effect(before,after):
    delta=n(after,'final_score')-n(before,'final_score');order_up=a(after,['paid_orders','orders'])>a(before,['paid_orders','orders']);revpar_up=n(after,'revpar')>n(before,'revpar');revenue_up=a(after,['room_revenue','store_revenue','revenue'])>a(before,['room_revenue','store_revenue','revenue'])
    if delta>0 and (order_up or revpar_up or revenue_up):return {'check_id':'O01','conclusion':'有效优化','next_action':'保留动作并进入复盘'}
    if delta>=10 and not (order_up or revpar_up or revenue_up):return {'check_id':'O02','conclusion':'疑似无效优化','next_action':'检查是否只优化基础项/页面项，未触达收益瓶颈'}
    if (n(after,'exposure')>n(before,'exposure') or n(after,'views')>n(before,'views')) and not (order_up or n(after,'payment_conversion_rate')>n(before,'payment_conversion_rate')):return {'check_id':'O03','conclusion':'流量质量或转化断点问题','next_action':'回到房型、权益、价格、点评检查'}
    if order_up and not (n(after,'adr')>n(before,'adr') or revpar_up or revenue_up):return {'check_id':'O04','conclusion':'低价跑量或低价房占比过高','next_action':'检查价格带、促销价、低价房占比'}
    if revenue_up and delta<3:return {'check_id':'O05','conclusion':'评分模型漏掉收益动作','next_action':'回调收益/价格/库存相关权重'}
    if n(after,'final_score')>=85 and (n(after,'revpar')<a(after,['peer_revpar','revpar_3m_avg'],n(after,'revpar')) or a(after,['paid_orders','orders'])<a(after,['peer_paid_orders','peer_orders'],a(after,['paid_orders','orders']))):return {'check_id':'O06','conclusion':'评分失真','next_action':'触发人工复核和模型权重调整'}
    return {'check_id':'O00','conclusion':'暂无显著变化','next_action':'继续观察7/14天趋势'}
