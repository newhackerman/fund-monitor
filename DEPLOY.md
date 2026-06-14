# 部署与运维指南

本文档说明 **ETF 轮动 + 风控监控器**（T+0动量强势策略）的部署、启动、配置和日常运维。

> 策略细节见 `rotation/REPORT.md`，候选池和参数见 `config/rotation.yaml`。
> 原"突破回踩"分钟监控（已确认无盈利）已备份为 `tools/legacy_*.bak`，不再推荐使用。

---

## 1. 系统要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11、Linux、macOS 均可 |
| Python | 3.10+（已在 3.13 测试通过） |
| 网络 | 需访问腾讯/新浪行情接口（行情数据）、企业微信 webhook（信号推送） |

### 依赖安装

```bash
pip install -r requirements.txt
```

核心依赖：
- `pandas` / `numpy` —— 数据处理、指标计算
- `requests` —— 行情拉取、企微推送
- `pyyaml` —— 配置读取
- `pyarrow` —— 日线数据 parquet 缓存
- `akshare` / `Ta-Lib` —— 旧监控用（新监控器不依赖，但保留以兼容）

---

## 2. 目录结构

```text
fund-monitor/
├── tools/
│   ├── daily_rotation_monitor.py   # ⭐ 新监控器（轮动+风控，主用）
│   ├── data_fetch.py               # 实时行情获取（腾讯/新浪）
│   ├── notifier.py                 # 企微/钉钉推送
│   ├── monitor.py                  # 旧监控器（突破回踩，已弃用）
│   ├── legacy_monitor.py.bak       # 旧监控备份
│   └── legacy_breakout_signals.py.bak
├── rotation/                       # 聚宽策略核心 + 回测
│   ├── strategy_momentum.py          # 打分、滤波器、震荡期、风控
│   ├── daily_data.py               # 日线数据（腾讯主源+新浪兜底）
│   ├── backtest.py                 # 回测引擎
│   ├── run.py                      # 回测入口
│   └── REPORT.md                   # 回测报告
├── config/
│   └── rotation.yaml               # ⭐ 主配置（候选池、参数、企微webhook）
├── data/
│   ├── daily_rotation_state.json   # 持仓状态（运行时生成，勿手删）
│   ├── daily_signals.json          # 信号历史
│   ├── daily_cache/*.parquet       # 日线缓存
│   └── daily_rotation_monitor.pid  # 进程 PID
├── logs/
│   └── daily_rotation_monitor.log  # 运行日志
├── run_rotation_monitor.bat        # ⭐ Windows 一键启动
└── requirements.txt
```

---

## 3. 首次部署步骤

### 步骤 1：安装依赖

```bash
pip install -r requirements.txt
```

### 步骤 2：配置企业微信推送

编辑 `config/rotation.yaml`，确认 `notify.wechat` 段：

```yaml
notify:
  wechat:
    enabled: true
    key: '你的企业微信webhook-key'   # 已配置
```

> 获取 webhook key：企业微信群 → 群机器人 → 添加机器人 → 复制 webhook URL 中 `key=` 后面的部分。

### 步骤 3：预拉日线数据（可选，加速首次启动）

首次启动会自动拉取 27 个标的的日线数据（约 20-30 秒）。如想提前拉好：

```bash
python -m rotation.run --start 2024-01-01
```

这会同时跑一次回测，验证策略和配置无误。数据缓存到 `data/daily_cache/`，后续启动零网络延迟。

### 步骤 4：启动监控器

**Windows（推荐）：**
```bash
run_rotation_monitor.bat
```

**通用命令行：**
```bash
python tools/daily_rotation_monitor.py start-bg
```

### 步骤 5：验证运行

```bash
run_rotation_monitor.bat status
# 或
python tools/daily_rotation_monitor.py status
```

应显示 `运行状态: 运行中`。

---

## 4. 监控器工作机制

监控器常驻运行，每个交易日执行两层逻辑：

### 4.1 日频轮动（每日 13:10 一次）

| 步骤 | 说明 |
|---|---|
| 打分 | 用最新日线 + 13:10 实时价，给 27 个候选 ETF 算动量分（加权对数回归 × R²） |
| 选股 | 选动量分最高的 1 只（`holdings_num: 1`） |
| 对比 | 与当前持仓对比，生成 BUY/SELL 信号 |
| 推送 | 有调仓 → 推企业微信；无调仓 → 静默 |

### 4.2 分钟级风控（交易时段每 30 秒，T+0 优势）

对当前持仓拉实时价，触发任一条件立即卖出并推送：

| 风控类型 | 触发条件 | 配置项 | 默认值 |
|---|---|---|---|
| **硬止损** | 亏损 ≤ 阈值 | `stop_loss_pct` | **-5%** |
| **止盈保护** | 浮盈 > 启动门槛后，从最高价回撤 ≥ 阈值 | `profit_protect_activate_pct` + `profit_protect_drawdown_pct` | **+2% 启动，5% 回撤** |

> 启动门槛（浮盈>2%）的设计目的：避免刚买入就被日内正常波动扫出。跨境 ETF 日内波动常达 ±3%，没有启动门槛会导致频繁误触发。

### 4.3 信号示例（企业微信收到）

```
ETF轮动调仓信号 2026-05-15 13:10

🔴 SELL 161226 @ 1.234 (浮盈+12.5%)
   轮动调出(动量下降)
🟢 BUY 513100 @ 2.165
   轮动买入(动量分:4.912)

> 候选池打分前3: 513100(4.91), 513050(3.82), 513130(2.14)
```

风控触发时：
```
ETF轮动调仓信号 2026-06-14 13:10

🔴 SELL 513100 @ 2.162
   硬止损(-9.1%<=-5%)
```

---

## 5. 配置详解（`config/rotation.yaml`）

### 5.1 候选池（`etf_pool`）

27 只 T+0 ETF（跨境权益 17 + 商品 6 + 债券 3 + 货币 1）。修改候选池直接编辑此列表。

> ⚠️ 新增标的必须是 T+0 品种（跨境/黄金商品/债券/货币 ETF），否则回测假设与实盘不符。

### 5.2 防御与基准

```yaml
defensive_etf: '511010'   # 无达标标的时切换到此（国债，低风险）
benchmark: '513100'       # 震荡期判断的基准指数
```

### 5.3 风控参数（`params.realtime_risk_control`）

```yaml
realtime_risk_control:
  enabled: true
  stop_loss_pct: -0.05              # 硬止损：亏损≤-5%立即卖
  profit_protect_activate_pct: 0.02 # 止盈启动门槛：浮盈>2%
  profit_protect_drawdown_pct: 0.05 # 止盈回撤：启动后从高点回撤≥5%卖
```

**调参建议（上线后观察 2-4 周再调）：**
- 被频繁扫出（过早卖出错过趋势）→ 调大 `profit_protect_drawdown_pct`（如 0.07）或调高启动门槛（如 0.03）
- 单笔亏损过大 → 收紧 `stop_loss_pct`（如 -0.03）
- 想关闭风控只用日频轮动 → `enabled: false`

### 5.4 企微推送（`notify.wechat`）

```yaml
notify:
  wechat:
    enabled: true
    key: 'bc6ae562-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
```

`enabled: false` 则只写 `data/daily_signals.json`，不推送。

---

## 6. 日常运维

### 6.1 常用命令

```bash
# 启动（后台）
run_rotation_monitor.bat
# 或
python tools/daily_rotation_monitor.py start-bg

# 查看状态（运行状态、当前持仓、上次触发）
python tools/daily_rotation_monitor.py status

# 停止
python tools/daily_rotation_monitor.py stop

# 立即跑一次轮动评估（测试用，会推送企微）
python tools/daily_rotation_monitor.py run-once

# 历史模拟（不推送、不改持仓状态）
python tools/daily_rotation_monitor.py dry-run --date 2026-05-15
```

### 6.2 查看日志

```bash
# 实时日志（Linux/macOS）
tail -f logs/daily_rotation_monitor.log

# Windows PowerShell
Get-Content logs\daily_rotation_monitor.log -Tail 50 -Wait
```

日志包含：每次风控检查、轮动评估、信号生成、推送结果。

### 6.3 持仓状态文件

`data/daily_rotation_state.json` 记录当前持仓和策略状态。**运行时勿手动删除**。

如果你有**已存在的实盘持仓**（监控器启动前就持有的），需要手动填入此文件，否则监控器不知道你持有什么：

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
- `max_price`：持仓以来最高价（用于止盈回撤判断，初始可设为 buy_price）
- `buy_idx`：买入日在日线数据中的下标（可填 0，风控不依赖此字段）

### 6.4 数据缓存更新

日线数据缓存在 `data/daily_cache/*.parquet`。监控器每日启动会自动增量更新当天数据。如需强制全量刷新：

```bash
# 删除缓存后重启监控器，会重新拉取
del data\daily_cache\*.parquet
python tools/daily_rotation_monitor.py stop
python tools/daily_rotation_monitor.py start-bg
```

### 6.5 进程管理（Windows 长期常驻）

`start-bg` 用 `pythonw.exe` 后台运行，关闭终端不会停止。但**重启电脑会停止**。如需开机自启：

**方案 A：任务计划程序（推荐）**
1. Win+R → `taskschd.msc`
2. 创建任务 → 触发器"登录时" → 操作"启动程序"
3. 程序：`pythonw.exe`，参数：`tools\daily_rotation_monitor.py start-bg`，起始于：项目根目录

**方案 B：NSSM 服务化**
```bash
nssm install FundRotationMonitor "C:\path\to\pythonw.exe" "tools\daily_rotation_monitor.py run-loop"
nssm start FundRotationMonitor
```

### 6.6 Docker 部署（跨平台推荐）

Docker 方式适合 Linux 服务器、NAS、或不想配 Python 环境的场景。`Dockerfile` 和 `docker-compose.yml` 已配置好，直接启动新监控器（轮动+风控）。

**首次部署：**

```bash
# 1. 确认 config/rotation.yaml 里的企微 webhook key 已填好
# 2. 构建并启动（后台）
docker compose up -d --build
```

**查看运行状态：**

```bash
# 容器状态
docker compose ps

# 实时日志（监控器的轮动评估、风控触发、推送结果）
docker compose logs -f
```

**停止/重启：**

```bash
docker compose stop          # 停止（持仓状态保留在 ./data 卷）
docker compose start         # 启动
docker compose restart       # 重启
docker compose down          # 停止并删除容器（数据卷保留）
```

**修改配置后生效：**

`config/rotation.yaml` 通过卷挂载，修改后**需重启容器**才生效：

```bash
docker compose restart
```

**数据持久化（已配置）：**

| 挂载卷 | 容器路径 | 作用 |
|---|---|---|
| `./data` | `/app/data` | 持仓状态、信号历史、日线缓存、PID |
| `./logs` | `/app/logs` | 运行日志 |
| `./config` | `/app/config` | 配置文件 |

容器删除重建后，持仓状态（`data/daily_rotation_state.json`）和日线缓存都不丢。

**Docker vs 本地部署的差异：**

| 项 | Docker | 本地（Windows .bat / python） |
|---|---|---|
| 环境隔离 | ✅ 完全隔离 | ❌ 依赖本机 Python |
| 重启自启 | ✅ `restart: unless-stopped` | 需配任务计划/NSSM |
| 调试便利 | 需 `docker logs` | 直接看终端 |
| 资源占用 | 略高（容器开销） | 低 |

**启用旧 webui（可选）：**

默认不启用 webui（它为旧监控设计，对新监控器数据展示意义有限）。如需启用，编辑 `Dockerfile` 取消 `EXPOSE 8787` 注释，并修改 `CMD` 同时启动两者；再在 `docker-compose.yml` 取消 `ports` 注释。

---

## 7. 回测验证

部署后建议跑一次回测，确认策略在你的环境表现符合预期：

```bash
python -m rotation.run --start 2024-01-01 --end 2026-06-12
```

输出：
- `rotation/REPORT.md` —— 人类可读报告（含基准对照、样本外验证、风险提示）
- `data/rotation_backtest_report.json` —— 结构化报告
- `data/rotation_equity_curve.csv` —— 净值曲线
- `data/rotation_trades.csv` —— 交易明细

**最近一次回测结果**（2024-01 ~ 2026-06，590 交易日）：
- 累计收益 +378.69%，年化 +89.79%，最大回撤 -21.38%，夏普 1.985
- 样本内 +47%、样本外 +225%，未发现过拟合

---

## 8. 故障排查

### 监控器启动后立即退出

```bash
# 查看日志
python tools/daily_rotation_monitor.py run-loop
```

前台运行会直接打印错误。常见原因：
- 依赖未装全 → `pip install -r requirements.txt`
- 配置文件语法错误 → 检查 `config/rotation.yaml` 缩进

### 收不到企微推送

1. 确认 `notify.wechat.enabled: true`
2. 确认 `key` 正确（在企微群机器人设置里复制完整 webhook URL）
3. 测试推送：`python tools/daily_rotation_monitor.py run-once`（会立即评估并推送）
4. 查日志是否 `企业微信推送: 成功`

### 风控不触发

1. 确认 `realtime_risk_control.enabled: true`
2. 确认 `data/daily_rotation_state.json` 里有持仓
3. 确认 `buy_price` 数值合理（不是 0 或异常值）
4. 手动验证：`python tools/daily_rotation_monitor.py status` 看当前持仓

### 行情数据拉取失败

腾讯/新浪接口偶发不稳定。监控器有 3 次重试。如持续失败：
- 检查网络（特别是公司代理）
- 删除 `data/daily_cache/` 强制重拉

---

## 9. 与旧监控的关系

| 项 | 旧监控（`tools/monitor.py`） | 新监控（`tools/daily_rotation_monitor.py`） |
|---|---|---|
| 策略 | 突破回踩（分钟级） | T+0动量强势策略（日频+分钟风控） |
| 实测表现 | 无盈利（已确认） | 回测年化 +90% |
| 状态 | 已备份为 `legacy_*.bak`，不再推荐 | ⭐ 主用 |
| 启动脚本 | `run_monitor_windows.bat` | `run_rotation_monitor.bat` |
| 配置 | `config/default.yaml` | `config/rotation.yaml` |

两套监控**可并存**（端口/文件不冲突），但建议只运行新监控。

---

## 10. 重要风险提示

1. **信号监控 ≠ 自动交易**：本系统只推送买卖建议到企业微信，**不连接券商、不自动下单**。你收到信号后需手动操作。
2. **回测期偏牛市**：2024-2026 跨境/商品 ETF 普涨，策略在趋势市表现好；**震荡/下跌市可能失效**。
3. **跨境 ETF 溢价风险**：513050/159509 等境外标的常现高溢价，回测未过滤。收到买入信号时建议人工查溢价率（>5% 谨慎）。
4. **流动性风险**：满仓单只，部分小盘跨境 ETF 成交额低，大资金冲击成本高。
5. **T+0 风控未经分钟回测验证**：分钟历史数据拉不到足够长度，风控阈值基于逻辑设定，建议上线后观察调参。
6. **不构成投资建议**，实盘交易自负盈亏。
