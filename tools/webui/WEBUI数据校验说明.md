# Web UI 数据校验说明（中文）

## 这次修复的重点
本次不是新增功能，而是优先修复“页面内部数据口径不一致”的问题。

## 修复思路
### 1. 页面核心卡片统一只读固定接口
- `/api/status`
- `/api/summary`
- `/api/logs`

不再让部分区域走旧字段、部分区域走旧逻辑。

### 2. 区分“读取失败”和“真实为 0”
例如：
- `watchlist_count = 0` 可能是错误，也可能是真实值
- 本次改成：如果字段没取到，显示 **读取失败**，而不是直接显示 0

### 3. 顶部新增接口健康状态
页面顶部会显示：
- `接口状态：status / summary 正常`
- 或 `接口状态：接口异常`

## 当前核心字段口径
### 实时状态
- 运行状态：`status.running`
- 监控基金数：`status.watchlist_count`
- PID：`status.pid`
- 日志更新时间：`status.latest_log_time`

### 最新交易日概览
- 最新交易日：`status.latest_trading_day`
- 信号数：`status.latest_day_signal_count`
- 交易数：`status.latest_day_trade_count`
- 平仓数：`status.latest_day_closed_count`
- 未平仓：`status.latest_day_open_count`
- 胜率：`status.latest_day_win_rate`
- 累计收益：`status.latest_day_sum_profit_pct`
- 平均收益：`status.latest_day_avg_profit_pct`

### 全部历史概览
- 总交易数：`status.total_trade_count`
- 总平仓数：`status.total_closed_count`
- 总未平仓：`status.total_open_count`
- 总胜率：`status.total_win_rate`
- 总累计收益：`status.total_sum_profit_pct`
- 总平均收益：`status.total_avg_profit_pct`

## 重要说明
如果页面仍然显示旧数据，通常不是策略数据错，而是：
- 浏览器缓存没刷新
- 容器/服务仍在跑旧版 Web UI 进程
- 访问到了旧端口或旧实例
