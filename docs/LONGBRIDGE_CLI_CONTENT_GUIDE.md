# Longbridge CLI 资讯层使用指南

## 当前接入状态

第一期已接入主分析链路的资讯层，覆盖：

- `news` -> `latest_news`
- `filing` -> `announcements`
- `consensus` -> `earnings`
- `institution-rating` -> `market_analysis`

`risk_check` 与 `industry` 继续由开放搜索链路补齐。

## 本地 smoke 验证

```bash
cd daily_stock_analysis
longbridge news AAPL.US --count 3 --format json
longbridge filing AAPL.US --format json
longbridge consensus AAPL.US --format json
longbridge institution-rating AAPL.US --format json
python -m pytest tests/test_longbridge_content_service.py tests/test_pipeline_longbridge_intel.py -q
```
