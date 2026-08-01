# T+0 基金 ETF 监控系统

基于 **T+0动量强势策略** 的 ETF 实时信号 + 风控监控器。

监控 27 只 T+0 标的（跨境/商品/债券/货币 ETF），每日 13:10 动量打分选股，
交易时段分钟级硬止损/止盈保护，信号实时推送到企业微信。

> 完整部署说明见 [DEPLOY.md](DEPLOY.md)
> 策略回测报告见 [rotation/REPORT.md](rotation/REPORT.md)
> 配置文件 [config/rotation.yaml](config/rotation.yaml)

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置企业微信 webhook（编辑 config/rotation.yaml 的 notify.wechat 段）

# 3. 启动监控（Windows）
run_rotation_monitor.bat
# 或：python tools/daily_rotation_monitor.py start-bg

# 4. 查看状态
python tools/daily_rotation_monitor.py status
```

Linux/macOS 用 `./run_rotation_monitor.sh`，Docker 用 `docker compose up -d --build`。
详见 [DEPLOY.md](DEPLOY.md)。

---

## 策略机制

监控器常驻运行，每个交易日执行两层逻辑：

### 1. 日频轮动选股（每日 13:10 一次）

用最新日线 + 13:10 实时价，给 27 个候选 ETF 算动量分（加权对数回归斜率年化 x R^2），叠加短期动量、单日跌幅、成交量异动、拉普拉斯/高斯动态滤波器、震荡期状态机等过滤条件。选动量分最高的 1 只，与当前持仓对比生成 BUY/SELL 调仓信号。无达标标的时切换到防御 ETF（国债 511010）。

### 2. 分钟级风控（交易时段每 30 秒，T+0 优势）

对当前持仓拉实时价，触发任一条件立即卖出并推送：

| 风控类型 | 触发条件 | 默认值 |
|---|---|---|
| 硬止损 | 亏损 <= 阈值 | -5% |
| 止盈保护 | 浮盈 > 启动门槛后，从最高价回撤 >= 阈值 | +2% 启动，5% 回撤 |

启动门槛（浮盈>2%）避免刚买入被日内噪音扫出。跨境 ETF 日内波动常达 +/-3%。

### 信号推送

有调仓/风控信号时推送到企业微信（仅推送，不自动下单）。无信号则静默。

信号示例（纯文本格式）：

```
ETF轮动信号
ETF轮动调仓信号 2026-07-31 13:10

卖出 513690(港股红利ETF博时) @ 1.145 (浮盈+0.35%)
   轮动调出(动量下降)
---------------
买入 501018(南方原油LOF) @ 1.985
   轮动买入(动量分:14.397)

候选池打分前3: 501018(南方原油LOF 14.40), 513100(纳指ETF国泰 7.37), 513400(道琼斯ETF鹏华 0.38)
```

风控触发时：

```
ETF轮动信号
ETF轮动调仓信号 2026-07-28 13:10

卖出 159985(豆粕ETF华夏) @ 2.176 (浮盈-5.14%)
   硬止损(-5.1%<=-5%)
```

推送可靠性机制：发送函数检查企业微信 errcode（非仅 HTTP 200），失败自动重试 10 次（间隔递增 2-4-8-16-30 秒），10 次仍失败休息 30 分钟后再试 1 次。先推送成功再更新持仓状态，避免推送失败导致卖出通知永久丢失。

---

## 候选池（27 只 T+0 ETF）

| 类别 | 数量 | 代表标的 |
|---|---|---|
| 跨境权益 | 17 | 纳指(513100)、标普500(513500)、恒生科技(513130)、中概互联(513050)、日经(513000) 等 |
| 商品 | 6 | 黄金(518880)、白银(161226)、原油(501018)、豆粕(159985) 等 |
| 债券 | 3 | 国债(511010)、城投债(511220)、可转债(511380) |
| 货币 | 1 | 自由现金流(159201) |

候选池构成说明：用户原始 35 个 T+0 标的 + 聚宽参考池的 T+0 标的，按跟踪指数去重到 27 个（每类保留流动性最好的一只）。详见 `config/rotation.yaml`。

> 候选池全部为 T+0 品种（跨境/商品/债券/货币 ETF），支持当日回转交易。新增标的必须也是 T+0，否则策略假设与实盘不符。

---

## 回测结果（2024-01 ~ 2026-06，590 交易日）

| 指标 | 值 |
|---|---|
| 累计收益 | +378.69% |
| 年化收益 | +89.79% |
| 最大回撤 | -21.38% |
| 夏普 | 1.985 |
| 相对等权池超额 | +329%（选股 alpha） |
| 样本外（2025-03~2026-06）年化 | +162.9% |

策略相对"等权全池买入持有"超额 +329%，收益主要来自选股轮动而非候选池 beta。样本内外分段都显著正收益，未发现过拟合。

完整报告：`rotation/REPORT.md`（含基准对照、样本外验证、风险提示）。

### 跑回测

```bash
python -m rotation.run --start 2024-01-01 --end 2026-06-12
```

输出文件：

| 文件 | 说明 |
|---|---|
| `rotation/REPORT.md` | 人类可读报告（含基准对照、样本外验证、风险提示） |
| `data/rotation_backtest_report.json` | 结构化报告 |
| `data/rotation_equity_curve.csv` | 净值曲线 |
| `data/rotation_trades.csv` | 交易明细 |

回测参数可在 `config/rotation.yaml` 的 `backtest` 段配置：

```yaml
backtest:
  start: '2024-01-01'
  end: '2026-06-12'
  initial_capital: 100000.0
  commission_rate: 0.0001   # 万一
  min_commission: 5.0
  slippage: 0.0001          # 万一
  trade_at: 'close'
```

---

## 常用命令

```bash
# 启动（后台常驻）
python tools/daily_rotation_monitor.py start-bg    # Windows/Linux 通用
run_rotation_monitor.bat                            # Windows 一键
./run_rotation_monitor.sh                           # Linux/macOS

# 查看状态（运行状态、当前持仓、心跳）
python tools/daily_rotation_monitor.py status

# 停止
python tools/daily_rotation_monitor.py stop

# 立即跑一次轮动评估（测试用，会推送）
python tools/daily_rotation_monitor.py run-once

# 用历史数据模拟某天信号（不推送、不改状态）
python tools/daily_rotation_monitor.py dry-run --date 2026-05-15

# 跑回测
python -m rotation.run --start 2024-01-01 --end 2026-06-12

# 查看实时日志
tail -f logs/daily_rotation_monitor.log              # Linux/macOS
Get-Content logs\daily_rotation_monitor.log -Tail 50 -Wait   # Windows PowerShell
```

---

## 风控参数（`config/rotation.yaml`）

```yaml
realtime_risk_control:
  enabled: true
  stop_loss_pct: -0.05              # 硬止损 -5%
  profit_protect_activate_pct: 0.02  # 浮盈>2% 才启动止盈保护
  profit_protect_drawdown_pct: 0.05 # 启动后从高点回撤5%卖出
```

调参建议（上线后观察 2-4 周再调）：

- 被频繁扫出 -> 调大 `profit_protect_drawdown_pct`（如 0.07）或调高启动门槛（如 0.03）
- 单笔亏损过大 -> 收紧 `stop_loss_pct`（如 -0.03）
- 想关闭风控只用日频轮动 -> `enabled: false`

---

## 配置说明（`config/rotation.yaml`）

### 候选池

```yaml
etf_pool:
  - '513100'   # 纳指ETF国泰
  - '513500'   # 标普500ETF博时
  # ... 共 27 只，全部 T+0
```

修改候选池直接编辑此列表。新增标的必须是 T+0 品种。

### 防御与基准

```yaml
defensive_etf: '511010'   # 无达标标的时切换到此（国债，低风险）
benchmark: '513100'       # 震荡期判断的基准指数
```

### 企微推送

```yaml
notify:
  wechat:
    enabled: true
    key: '你的企业微信webhook-key'
```

`enabled: false` 则只写 `data/daily_signals.json`，不推送。获取 webhook key：企业微信群 -> 群机器人 -> 添加机器人 -> 复制 webhook URL 中 `key=` 后面的部分。

---

## 目录结构

```text
fund-monitor/
├── tools/
│   ├── daily_rotation_monitor.py   # 实时信号+风控监控器（主用）
│   ├── data_fetch.py               # 实时行情获取（腾讯/新浪）
│   ├── notifier.py                 # 企业微信/钉钉推送（含重试机制）
│   ├── signals.py                  # 信号格式化
│   ├── indicators.py               # 技术指标
│   ├── monitor.py                  # 旧监控器（突破回踩，已弃用）
│   └── legacy_*.bak                # 旧策略备份
├── rotation/                       # T+0动量强势策略核心 + 回测
│   ├── strategy_momentum.py        # 打分、滤波器、震荡期、风控
│   ├── daily_data.py               # 日线数据（腾讯主源+新浪兜底，parquet缓存）
│   ├── backtest.py                 # 日线回测引擎
│   ├── run.py                      # 回测入口
│   └── REPORT.md                   # 回测报告
├── config/
│   └── rotation.yaml               # 候选池、风控参数、企微webhook
├── data/                           # 持仓状态、信号历史、日线缓存（运行时生成）
│   ├── daily_rotation_state.json   # 持仓状态（勿手删）
│   ├── daily_signals.json          # 信号历史
│   └── daily_cache/*.parquet       # 日线缓存
├── logs/                           # 运行日志
├── DEPLOY.md                       # 完整部署运维文档
├── Dockerfile / docker-compose.yml # Docker 部署
├── run_rotation_monitor.bat        # Windows 启动脚本
├── run_rotation_monitor.sh         # Linux/macOS 启动脚本
└── requirements.txt
```

---

## 持仓状态文件

`data/daily_rotation_state.json` 记录当前持仓和策略状态。运行时勿手动删除。

如果你有已存在的实盘持仓（监控器启动前就持有的），需要手动填入此文件：

```json
{
  "holdings": [
    {
      "code": "513100",
      "shares": "target",
      "buy_price": 2.15,
      "max_price": 2.20,
      "buy_date": "2026-06-10",
      "buy_idx": 635
    }
  ],
  "last_trigger_date": null,
  "strategy_state": {}
}
```

- `buy_price`：你的实际买入成本
- `max_price`：持仓以来最高价（用于止盈回撤判断，初始可设为 buy_price，监控器每 30 秒自动更新）
- `buy_idx`：买入日在日线数据中的下标（可填 0，风控不依赖此字段）

---

## 故障排查

**监控器启动后立即退出**

前台运行查看错误：`python tools/daily_rotation_monitor.py run-loop`。常见原因：依赖未装全、配置文件缩进错误。

**收不到企微推送**

1. 确认 `notify.wechat.enabled: true` 且 `key` 正确
2. 测试推送：`python tools/daily_rotation_monitor.py run-once`
3. 查日志是否 `企业微信推送: 成功`
4. 推送失败会自动重试 10 次 + 30 分钟后再试 1 次，查日志确认重试结果

**风控不触发**

1. 确认 `realtime_risk_control.enabled: true`
2. 确认 `data/daily_rotation_state.json` 里有持仓且 `buy_price` 合理
3. `python tools/daily_rotation_monitor.py status` 看当前持仓

**行情数据拉取失败**

腾讯/新浪接口偶发不稳定，监控器有重试机制。如持续失败：检查网络（特别是公司代理）、删除 `data/daily_cache/` 强制重拉。

---

## 重要约定

1. 信号监控 != 自动交易：只推送买卖建议到企业微信，不连接券商、不自动下单。收到信号后手动操作。
2. 首次运行从空仓开始。如已有实盘持仓，需手动填入 `data/daily_rotation_state.json`。
3. 跨境 ETF 溢价风险：收到买入信号时建议人工查溢价率（>5% 谨慎），回测未过滤。
4. 回测期偏牛市：2024-2026 跨境/商品 ETF 普涨，震荡/下跌市表现未知。
5. 不构成投资建议，实盘交易自负盈亏。
