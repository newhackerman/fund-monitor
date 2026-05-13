# Web UI 字段说明（中文）

## 实时状态
### 运行状态
来源：`data/monitor.pid` + 进程存活检查

### 监控基金数
来源：`data/watchlist.json`

### 日志更新时间
来源：`logs/monitor.log` 文件修改时间

### PID
来源：`data/monitor.pid`

## 最新交易日概览
### 最新交易日
来源：`trades.json` 或 `signals.json` 中最新日期

### 信号数
来源：`signals.json` 中该交易日记录数

### 交易数
来源：`trades.json` 中该交易日记录数

### 平仓数
来源：`trades.json` 中 `type=SELL`

### 未平仓
来源：`trades.json` 中 `type=BUY and status=OPEN`

### 胜率 / 累计收益 / 平均收益
来源：该交易日 `SELL` 记录中的 `profit_pct`

## 全部历史概览
来源：`trades.json` 全部记录

## OPEN 持仓浮盈浮亏
来源：
- 买入价：`trades.json` 中 OPEN BUY 的 `price`
- 最新价：`data/minute_cache/<code>_<day>.json` 最后一条 close
- 浮盈亏%：按以上两者估算

说明：
- 这不是逐秒实时行情
- 是按最近分钟缓存最后价估算

## 最近新增信号 / 最近 1 小时信号
来源：`signals.json`

## 按代码聚合视图
来源：最新交易日的 `signals.json + trades.json` 聚合

## 日志区
来源：`logs/monitor.log` 最后 150 行
