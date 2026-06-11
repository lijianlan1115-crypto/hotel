# 渠道 API 适配策略

## 1. 结论

当前 API 尚未最终确定。Beyondh、美团、订单来了、数据库、RPA、人工上传、样例数据都只作为数据来源进入统一数据契约。P0/P1 不依赖任何单一 API 正式开通。

本项目采用“代码运行时 + 中文 skill”混合架构：API 请求、签名、字段映射、状态码、身份权限和 dry-run 动作由脚本固化；业务解释、追问、飞书回复和审批沟通由 skill/模型完成。

## 2. 数据源类型

| 字段 | 可选值 | 说明 |
| --- | --- | --- |
| `adapter_vendor` | `beyondh`、`meituan`、`dindanll`、`xhotel`、`manual`、`database` | 实际适配来源 |
| `channel_source` | `meituan`、`feizhu`、`douyin`、`ctrip`、`wechat`、`pms`、`manual` | 业务渠道或数据归属 |
| `data_source_type` | `meituan_api`、`beyondh_api`、`dindanll_api`、`sqlite_db`、`mysql_db`、`postgres_db`、`rpa`、`manual_upload`、`sample_data` | 实际采集方式 |
| `source_capability` | `read_only`、`write_dry_run`、`write_live_pending`、`unavailable` | 当前能力状态 |
| `field_quality` | `confirmed`、`inferred`、`manual_required`、`unavailable` | 字段可信度 |

## 3. 美团 API 定位

美团 `developer.meituan.com/docs/api` 是美团技术服务合作中心 API 文档入口，具体接口需账号和业务权限确认。

美团酒店门票分销平台提供国内酒店 API、境外酒店 API、门票 API 等分销接入方式，但偏供给/分销预订链路，不等同于酒店商家侧 OTA 运营后台 API。

因此，美团在本项目中的定位是：

- 作为 `meituan_api` 参考来源。
- 优先补充 OTA 健康、流量转化、价格、评论和活动字段。
- 未授权时用后台导出、截图识别、RPA 或人工上传兜底。

## 4. P0/P1 美团优先字段

- HOS 总分及构成。
- 房型可售状态。
- 每日挂牌价。
- 每日促销价。
- 每日已售房量。
- 每日可售房量。
- 曝光量。
- 浏览人数。
- 支付转化率。
- 订单量。
- 评分、差评率、评价内容。

## 5. P2 美团字段

- 活动配置。
- 推广余额。
- 推广消耗。
- 竞品价格。
- 竞品活动。
- 同行排名。
- 客户订单画像。

## 6. Beyondh 定位

Beyondh 作为 PMS/API 参考来源，适合承接房型、房价、房态、订单和价格写入 dry-run。因为 API 是否最终采用未确定，P0/P1 验收只要求能生成 dry-run 请求并脱敏记录，不要求 live 调价。

## 7. 订单来了定位

订单来了开放平台作为 `dindanll_api` 参考来源，定位是 PMS/直连中台适配器，不是 OTA 渠道。它适合提供：

- PMS 酒店、房型、静态信息查询。
- 房价码、房型价格、房型库存查询。
- 订单查询、可订检查、接单/拒单/取消等直连业务参考。
- 房价、房态、订单状态变更推送事件参考。

订单来了涉及 RSA2/SHA1withRSA 签名验签、AES 解密、门店调用凭证和推送回调。P0/P1 只做 dry-run 请求构造和字段归一化；真实签名、验签、token 刷新和回调处理必须等账号、密钥、回调地址确认后再启用。

## 8. 脚本固化边界

必须脚本化：

- 签名验签、token、请求构造、字段映射、状态码转换。
- 数据库只读连接、白名单 SQL 模板、字段映射和 DSN 脱敏。
- JSON schema 或统一数据契约校验。
- 飞书身份校验、审批拦截、日志脱敏、dry-run 动作生成。

半脚本化：

- 需求指数、OTA 健康分、销售基准线、偏差诊断、调价安全阈值。

保留给 skill/模型：

- 业务解释、缺失信息追问、飞书回复、策略取舍、评论回复草稿、admin/owner 审批沟通。

## 9. RPA 与人工上传兜底

当 API 不可用时：

- 数据库来源可优先读取已有 PMS/OTA/中台库，但必须只读并走白名单模板。
- MySQL 报表库通过 `database-source.json` 多 profile 映射 `import_batches`、`fact_room_fee_daily`、`fact_room_status_snapshot`、`fact_daily_metrics`、`fact_monthly_metrics`；字段变化时改配置，不改 skill。
- RPA 负责从后台读取或执行标准化流程。
- 人工上传负责导入截图、Excel、CSV 或飞书消息。
- 样例数据负责演示和开发自测。

所有方式必须输出统一字段，skill 不直接关心来源。

## 10. Runtime 验收命令

```bash
python runtime/hotel_ota_runtime.py adapter-request --adapter meituan --path /pms/priceinve/getRoomPrice --biz-content '{"hotelId":600000001,"channel":"MeiTuanEBK","roomTypeIds":["KING"]}'
python runtime/hotel_ota_runtime.py adapter-request --adapter dindanll --path /open/pms/third/ari/price --biz-content '{"hotelNum":10001,"roomTypeCodeList":[9001],"rateCode":30}'
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-price
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode columns --table fact_daily_metrics
python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template operating_snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template price_snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py database-query --db-kind sqlite --template order_snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template price_snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template order_snapshot --hotel-id puyue
```

## 11. 验收口径

2026-06-15 的验收重点：

- API 未确定时仍能回答“怎么跑”。
- S2/S4/S5/S14 能读取统一字段并产出快照、需求指数、调价建议、健康诊断。
- S6 只做 dry-run 和审批保护。
- 美团字段样例可以进入统一数据契约。
- 订单来了房价、库存、订单样例可以进入统一数据契约。
- 数据库只读来源可以进入统一数据契约，且未知模板或自由 SQL 必须阻断；MySQL 映射未确认前返回 `database_mapping_required`。
