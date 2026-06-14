# T+0 基金 ETF 监控系统

> ## ⭐ 当前推荐方案：ETF 轮动 + 风控监控器（聚宽七星高照策略移植）
>
> 旧的"突破回踩"分钟监控经实盘验证**无盈利**，已备份为 `tools/legacy_*.bak`。
> 新监控器基于聚宽策略，回测年化 +90%（2024-2026），且充分利用 T+0 标的当日可买卖的优势
> 做分钟级硬止损/止盈保护。
>
> **快速开始：**
> ```bash
> pip install -r requirements.txt
> run_rotation_monitor.bat              # Windows 一键启动
> # 或：python tools/daily_rotation_monitor.py start-bg
> ```
>
> 📋 完整部署说明见 **[DEPLOY.md](DEPLOY.md)**
> 📊 策略回测报告见 **[rotation/REPORT.md](rotation/REPORT.md)**
> ⚙️ 配置文件 **[config/rotation.yaml](config/rotation.yaml)**

---

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

> ⚠️ 以上为**旧监控**（突破回踩）的说明，该策略已确认无盈利，保留供历史参考。
> 新监控器见本 README 顶部的推荐方案，或 `rotation/` 目录。

> 建议：
> - 做“回测和实时是否对齐”的验证时，用 `first`
> - 做“是否还有优化空间”的研究时，再看 `best`

---

## 快速开始

### 0. 启动 ETF 轮动监控（推荐）

```bash
pip install -r requirements.txt
run_rotation_monitor.bat              # Windows
# 或：python tools/daily_rotation_monitor.py start-bg
```

详见 [DEPLOY.md](DEPLOY.md)。

### 1. 启动监控（旧版，突破回踩，不推荐）

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

## 日线 ETF 轮动策略（`rotation/`，独立于 T+0 监控）

T+0 分钟监控是日内框架，但部分聚宽策略本质是**日线 T+1 轮动**（持仓多日），
强行塞进分钟引擎会变形。因此项目提供独立的 `rotation/` 子包，
作为"预留策略接口"的第一个实现，**不污染**现有 `tools/monitor.py` / `signals.py`。

### 当前已实现：七星高照 ETF 轮动（移植自聚宽）

来源：聚宽 king088 / 晨曦量化 / 在水一方ly（joinquant:72393/70329/69163）。
核心逻辑：25 日加权对数回归动量分 × R²，叠加拉普拉斯/高斯动态滤波器、
震荡期状态机、盈利保护、防御 ETF 轮动。

### 目录

```text
rotation/
├── daily_data.py        # 日线数据（腾讯主源 + 新浪兜底，本地 parquet 缓存）
├── strategy_qixing.py   # 策略核心：打分 + 滤波器 + 震荡期 + 盈利保护
├── backtest.py          # 回测引擎：T+1、等权、防御ETF、涨跌停、交易成本
├── run.py               # 入口：拉数据 -> 回测 -> 报告
└── REPORT.md            # 最新回测报告（人类可读）
config/rotation.yaml     # 策略参数（预留接口，便于新增策略对比）
```

### 用法

```bash
# 首次运行：拉取 39 个 ETF 日线（约 20 秒），缓存到 data/daily_cache/
python -m rotation.run

# 自定义区间
python -m rotation.run --start 2024-01-01 --end 2026-06-12

# 强制刷新数据
python -m rotation.run --refresh
```

输出：
- `rotation/REPORT.md` —— 人类可读报告（含基准对照、样本外验证、风险提示）
- `data/rotation_backtest_report.json` —— 结构化完整报告
- `data/rotation_equity_curve.csv` —— 净值曲线
- `data/rotation_trades.csv` —— 交易明细

### 回测结论摘要（2024-01 ~ 2026-06）

| 指标 | 值 |
|---|---|
| 累计收益 | +403.24% |
| 年化收益 | +93.71% |
| 最大回撤 | -20.74% |
| 夏普 | 1.893 |
| 相对等权池超额 | +346.7% |
| 样本外（2025-03~2026-06）年化 | +154.8% |

**关键判读**：策略相对"等权全池买入持有"超额 +346%，说明收益主要来自**选股轮动**
而非候选池 beta；样本内外分段都显著正收益，未发现过拟合迹象。

**已知局限**（详见 REPORT.md）：回测期偏牛市、跨境 ETF 溢价风险未过滤、
满仓单只的流动性风险。**不构成投资建议。**

### 预留接口：新增策略

后续要对比其他策略（如均线趋势、波动率目标），只需新增 `rotation/strategy_xxx.py`，
实现 `score_etf(...)`，在 `config/rotation.yaml` 加一段配置，复用 `backtest.py` 引擎即可。

### 实盘信号监控（每日 13:10 推送）

`tools/daily_rotation_monitor.py` 是基于聚宽策略的**实时信号+风控监控器**：

**两层机制（充分利用 T+0 标的当日可买卖的优势）：**

| 机制 | 频率 | 触发时点 | 作用 |
|---|---|---|---|
| **日频轮动** | 每日 1 次 | 13:10 | 打分选最强 ETF，生成 BUY/SELL 调仓信号 |
| **分钟级风控** | 每 30 秒 | 全交易日 | 对持仓拉实时价，硬止损/止盈保护即时触发 |

- 日频轮动：用最新日线 + 13:10 实时价给 27 个候选 ETF 打分 → 对比目标持仓与当前持仓 → 调仓
- 分钟级风控（T+0 优势核心）：
  - **硬止损**：买入后亏损 ≤ -5% 立即卖出（`stop_loss_pct`）
  - **止盈保护**：浮盈 > +2% 后启动，从持仓最高价回撤 ≥ 5% 卖出（`profit_protect_activate_pct` + `profit_protect_drawdown_pct`）
  - 启动门槛避免刚买入被日内噪音扫出
- 有信号 → 推送**企业微信**（仅推送，不自动下单）
- 持仓状态持久化到 `data/daily_rotation_state.json`，重启不丢

```bash
# 后台常驻运行（推荐）—— 日频 13:10 轮动 + 分钟级风控
python tools/daily_rotation_monitor.py start-bg

# 查看状态和当前持仓
python tools/daily_rotation_monitor.py status

# 停止
python tools/daily_rotation_monitor.py stop

# 立即跑一次轮动评估（会推送，测试用）
python tools/daily_rotation_monitor.py run-once

# 用历史数据模拟某天信号（不推送、不改状态）
python tools/daily_rotation_monitor.py dry-run --date 2026-05-15
```

**风控参数**（`config/rotation.yaml` → `params.realtime_risk_control`）：

```yaml
realtime_risk_control:
  enabled: true
  stop_loss_pct: -0.05              # 硬止损 -5%
  profit_protect_activate_pct: 0.02 # 浮盈>2% 才启动止盈保护
  profit_protect_drawdown_pct: 0.05 # 启动后从高点回撤5%卖出
```

**重要约定**：
- 这是**信号监控器**，只推送买卖建议，不连接券商、不实际下单
- 原 `tools/monitor.py`（分钟级突破回刺，已确认无盈利）已备份为 `tools/legacy_monitor.py.bak`
- 推送内容只含调仓/风控指令，无信号则静默
- 配置：`config/rotation.yaml` 的 `notify.wechat` 段

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
