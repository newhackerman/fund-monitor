# T+0 基金分钟级实时监控系统

## 当前状态

当前版本的 `fund-monitor` 已完成这几项收敛：

- 实时监控与回测脚本共用同一套买点引擎
- 买点主逻辑为 **突破后首次回踩（breakout_pullback）**
- 回测支持两种口径：
  - `first`：每个标的**首次触发**（用于对齐实时信号）
  - `best`：每个标的**最佳评分时点**（用于研究更优入场）
- 一致性检查支持直接验证：
  - 实时逐分钟重放 vs 回测结果
- 已补充**标准统计脚本**，用于统一报告口径

> 建议：
> - 做“回测和实时是否对齐”的验证时，用 `first`
> - 做“是否还有优化空间”的研究时，再看 `best`

---

## 快速开始

### 1. 启动监控

```bash
python3 skills/fund-monitor/tools/monitor.py start-bg
```

### 2. 查看状态

```bash
python3 skills/fund-monitor/tools/monitor.py status
```

### 3. 停止监控

```bash
python3 skills/fund-monitor/tools/monitor.py stop
```

---

## 标准统计 / 简报脚本

为了避免外部报告脚本各自猜口径，当前仓库提供两个标准脚本：

### 1. 结构化统计 JSON

```bash
python3 scripts/fund_monitor_stats.py
```

输出内容包括：
- 去重后的信号数
- 当前持仓数
- 已完成交易数
- 胜率
- 收益率盈亏比
- 金额盈亏比
- 已实现累计收益率
- 已实现累计收益

### 2. 简版日报 / 推送摘要

```bash
python3 scripts/fund_monitor_brief.py
```

适合做：
- Telegram / 企业微信 / Markdown 简报
- 定时巡检摘要
- 人工复盘时快速查看当前状态

---

## 统计口径说明（重要）

请统一按下面口径理解数据：

### 1. signals.json
- 用途：**信号事件流**
- 适合看：
  - 最新 BUY / SELL 触发
  - 信号原因
  - 触发时指标
- 不适合直接当“最终交易统计表”

### 2. trades.json
- 用途：**仓位 / 闭环交易记录**
- 适合看：
  - 当前持仓：`BUY + OPEN`
  - 已完成交易：`SELL + CLOSED`
  - 胜率 / 盈亏比 / 累计收益

### 3. 推荐统一定义
- **当前持仓数** = `trades.json` 中 `BUY + OPEN`
- **已完成交易数** = `trades.json` 中 `SELL + CLOSED`
- **胜率 / 盈亏比 / 累计收益** = 全部基于 `SELL + CLOSED`

### 4. 午休时段说明
当前监控会在午休时段跳过检查：
- `11:30 - 13:00`

所以如果某笔仓位在 11:30 前开出，午休期间看到它仍是 `OPEN`，通常是**预期行为**，不一定是异常。下午开盘后会继续评估卖出条件。

---

## Windows 启动说明

Windows 下建议优先使用：

```powershell
python skills/fund-monitor/tools/monitor.py start-bg
```

说明：

- `start` = 前台运行，PowerShell 窗口关掉后进程会一起结束
- `start-bg` = 后台拉起独立进程；Windows 下当前默认走 `keepalive -> worker` 守护链，降低 worker 异常退出后的中断风险
- `start-bg` 启动后，建议立刻执行一次：

```powershell
python skills/fund-monitor/tools/monitor.py status
```

如果后台启动后仍显示未运行，请查看：

```text
skills/fund-monitor/logs/monitor_stdout.log
skills/fund-monitor/logs/monitor.log
```

如果本机环境下仍会自动退出，下一步建议改成：

- Windows 任务计划程序（推荐）
- NSSM / WinSW 服务化

也就是说，当前 `start-bg` 已尽量规避 PowerShell 会话绑定问题，但**“长期常驻”最终最稳的仍然是计划任务或服务化**。

---

## 当前实时策略

### 买入逻辑：突破后首次回踩

核心条件：

- 只在允许时段内触发：
  - 09:45 - 10:35
  - 13:10 - 14:05
- 趋势过滤通过：
  - `close >= ma20`
  - `ma5 >= ma10 >= ma20`
- 回踩后再企稳：
  - `re_stabilize = True`
- RSI 强势但不过热：
  - `56 <= RSI <= 72`
-  保持趋势区：
  - `50 <= _K <= 82`
- 成交量不过弱：
  - `volume_ratio >= 1.02`
- MACD 不走坏：
  - `DIF >= DEA`
  - `DIF >= prev_DIF`
- 不追高：
  - `-0.05 <= ma5_gap_pct <= 0.12`
- 必须满足“突破后回踩”：
  - `0.05 <= pullback_pct <= 0.45`
  - `breakout_strength_pct >= 0.2`

### 卖出逻辑

当前卖出逻辑已按最新口径收敛为用户指定的 4 条主规则：

- 固定止盈：盈利达到 `5%` 强制平仓
- 固定止损：亏损达到 `-1%` 强制平仓
- 盈利回撤：一旦出现过盈利，从最高浮盈回撤 `1%` 强制平仓
- 超时强平：持仓超过 `20` 分钟强制平仓

补充说明：

- `allow_overnight: false` 时，如发现跨日 OPEN 仓，会触发“跨日补救强制平仓”
- 当前实际生效参数以 `skills/fund-monitor/config/default.yaml` 为准

---

## 回测脚本

### 1. 按首次触发回测（推荐）

用于和实时监控对齐：

```bash
python3 scripts/fund_monitor_breakout_backtest.py --day 2026-03-25 --mode first
```

### 2. 按最佳评分回测

用于研究更优入场点：

```bash
python3 scripts/fund_monitor_breakout_backtest.py --day 2026-03-25 --mode best
```

### 3. 同时输出 first / best

```bash
python3 scripts/fund_monitor_breakout_backtest.py --day 2026-03-25 --mode both
```

---

## 一致性检查

### 检查实时逐分钟重放与回测是否一致

```bash
python3 scripts/fund_monitor_consistency_check.py --day 2026-03-25 --mode both
```

输出说明：

- `FIRST_TRIGGER`
  - 用于验证“实时信号”和“回测信号”是否真正对齐
- `BEST_OR_LATEST`
  - 用于比较更激进/更优的候选时点

如果 `FIRST_TRIGGER` 下：

- `intersection = runtime_count = backtest_count`

则说明：

> 回测和实时信号已经对齐。

---

## 配置项说明

主配置文件：

```bash
skills/fund-monitor/config/default.yaml
```

重点参数：

### 监控

- `monitor.interval`：检查间隔（秒）
- `monitor.warmup_on_start`：启动时是否预热分钟缓存
- `monitor.warmup_periods_1m`：预热分钟数

### 买点参数

- `signals.buy.allowed_sessions`
- `signals.buy.disable_new_buy_after`
- `signals.buy.trend_rsi_min`
- `signals.buy.trend_rsi_max`
- `signals.buy.trend_volume_ratio`
- `signals.buy.max_chase_above_ma5_pct`
- `signals.buy.breakout_min_pct`
- `signals.buy.pullback_min_pct`
- `signals.buy.pullback_max_pct`
- `signals.buy.require_breakout_persistence_pct`
- `signals.buy.min_rebound_strength_pct`
- `signals.buy.min_recent_green_ratio`
- `signals.buy.min_ma5_slope_pct`
- `signals.buy.min_ma10_slope_pct`
- `signals.buy.max_price_above_prev_high_pct`

### 卖点参数

- `signals.sell.min_hold_minutes`
- `signals.sell.ma_turn_min_hold_minutes`
- `signals.sell.macd_sell_profit_floor_pct`
- `signals.sell.breakeven_trigger_pct`
- `signals.sell.breakeven_buffer_pct`
- `signals.sell.profit_protect_trigger_pct`
- `signals.sell.profit_protect_ma5_buffer_pct`
- `signals.sell.force_flat_after`
- `signals.sell.hard_flat_after`

### ATR 风控

- `signals.atr.stop_loss_multiplier`
- `signals.atr.take_profit_multiplier`
- `signals.atr.min_stop_loss_pct`
- `signals.atr.max_stop_loss_pct`

---

## 目录说明

```text
skills/fund-monitor/
├── tools/
│   ├── monitor.py          # 实时监控入口
│   ├── data_fetch.py       # 分钟数据获取与缓存
│   ├── indicators.py       # 指标计算与上下文提取
│   ├── signals.py          # 纯信号判断 + 交易状态约束
│   └── notifier.py         # 通知推送
├── config/
│   └── default.yaml        # 主配置
├── data/
│   ├── watchlist.json      # 监控列表
│   ├── signals.json        # 当天信号
│   ├── trades.json         # 交易状态/平仓记录
│   └── minute_cache/       # 分钟缓存
└── logs/
    └── monitor.log         # 运行日志
```

---

## 当前结论

如果你关注的是：

### 1. “实时信号和回测是否一致？”
看：

- `fund_monitor_consistency_check.py --mode first`

### 2. “还有没有更优入场空间？”
看：

- `fund_monitor_breakout_backtest.py --mode best`

这两个问题现在已经被拆开，不再混在一起。
