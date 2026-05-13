# FUND MONITOR PROGRESS - 2026-03-30

## 今天继续推进的内容

### 一、接续昨天进度，优先处理 Windows 后台常驻问题
今天先重新打开并检查了：
1. `skills/fund-monitor/tools/monitor.py`
2. `skills/fund-monitor/README.md`
3. `skills/fund-monitor/FUND_MONITOR_PROGRESS_2026-03-29.md`

目标仍然是昨天定下来的第一优先级：
- 继续收敛 Windows / PowerShell 下 `start-bg` 启动后可能自动退出的问题
- 至少先把后台启动路径做得更稳，并补上更明确的自检与排障说明

### 二、monitor.py 的后台启动逻辑增强
已对 `skills/fund-monitor/tools/monitor.py` 做了一轮增强：

1. 新增：
   - `STDOUT_LOG_FILE = logs/monitor_stdout.log`
2. 新增后台启动确认函数：
   - `_wait_for_background_pid()`
   - 用于在 `start-bg` 发起后等待 PID 文件落盘并确认进程存活
3. 新增后台启动命令构造函数：
   - `_build_start_command_for_background()`
   - Windows 下优先尝试 `pythonw.exe`
   - 如果不存在，则回退到当前 `sys.executable`
4. 强化 Windows 后台创建参数：
   - 保留 `CREATE_NEW_PROCESS_GROUP`
   - 保留 `DETACHED_PROCESS`
   - 新增 `CREATE_NO_WINDOW`
   - 保留 `stdin=DEVNULL`
   - 保留 `close_fds=True`
5. `start-bg` 现在不再只是“发起后 sleep 4 秒碰运气”，而是：
   - 先记录 launcher pid
   - 最长等待 15 秒确认 `monitor.pid`
   - 成功则明确输出后台 PID
   - 失败则引导查看：
     - `skills/fund-monitor/logs/monitor_stdout.log`
6. 对日志文件句柄做了 `finally` 清理，避免父进程残留打开句柄

### 三、README 补充 Windows 使用说明
已更新 `skills/fund-monitor/README.md`，新增：
- Windows 优先使用 `start-bg`
- `start` 只是前台运行，关掉 PowerShell 会一起退出
- `start-bg` 后立即用 `status` 检查
- 若失败，查看：
  - `skills/fund-monitor/logs/monitor_stdout.log`
  - `skills/fund-monitor/logs/monitor.log`
- 明确写出：
  - 如果仍不稳，最终更推荐 **任务计划程序 / 服务化**

### 四、当前判断
这次修改解决的是：
- **后台启动路径不够稳、缺少明确确认机制、缺少 Windows 专门兜底提示** 这几个问题

但还没有拿到 Windows 真机上的最终结论，所以现在的判断是：

#### 已改善
- `start-bg` 的实现比昨天更接近“真正的 detached 后台”
- Windows 下会优先尝试 `pythonw.exe`
- 失败时有更明确的日志落点和排障路径

#### 仍待验证
- 在用户本地 Windows / PowerShell 环境里是否已经能长期稳定常驻
- 是否仍存在：
  - 环境变量差异
  - Python 安装方式差异
  - PowerShell 启动上下文差异
  - 依赖初始化后异常退出

如果用户本地依然不稳定，下一步大概率应该进入：
- **任务计划程序方案**
- 或 **NSSM / WinSW 服务化方案**

## 今天新增推进（Linux 实盘 + 策略修复）

### 五、已在当前 Linux/OpenClaw 环境启动并确认 monitor
已执行：
- `python3 skills/fund-monitor/tools/monitor.py start-bg`
- `python3 skills/fund-monitor/tools/monitor.py status`

结果：
- monitor 成功启动
- 当前 Linux 环境后台运行正常
- 后续又在更新配置后完成了一次 stop / restart，当前仍正常运行

### 六、定位并修复 signals.json 重复 BUY 写入问题
已定位到 `skills/fund-monitor/tools/signals.py` 中一个明确 bug：
- `sync_signal_states()` 里处理 BUY 时，去重判断误写成了拿 BUY 去和 `SELL` 比较
- 结果导致同一条 BUY 信号被重复追加到 `signals.json`

已修复为：
- BUY 只与 BUY 按 `(type, code, time, reason)` 去重
- SELL 只与 SELL 按 `(type, code, time, reason)` 去重

同时已对当前 `skills/fund-monitor/data/signals.json` 做了一次去重清理：
- 清理前：2 条
- 清理后：1 条

### 七、发现“实盘配置”和“脚本默认逻辑”存在明显漂移
今天很关键的一点是确认了：
- `monitor.py` 实盘实际读取的是 `skills/fund-monitor/config/default.yaml`
- 但该 YAML 中的卖出逻辑参数，和 `signals.py` 默认逻辑已经明显不一致

特别是之前 YAML 里实际是：
- `use_ma_turn_exit: false`
- `profit_protect_trigger_pct: 999.0`
- `breakeven_trigger_pct: 999.0`
- `min_profit_for_ma5_exit_pct: 999.0`
- `ma10_turn_exit_on_loss: false`

这意味着：
- 回放研究看到的是一套逻辑
- 实盘 monitor 实际跑的是另一套逻辑
- 这会直接导致“回测/分析结论”和“真实落地表现”错位

### 八、卖出侧 A/B 调参：MA5 拐头至少持有 6 分钟再触发
针对 3/27 亏损样本，今天做了一轮很小但有效的改动：
- 在 `signals.py` 中新增：
  - `sell.ma_turn_min_hold_minutes`
- 对 `MA5 拐头止盈 / 止损` 增加前置门槛：
  - 至少持有 `6` 分钟后，才允许 MA5 拐头触发退出

核心目的：
- 避免买入后 1~3 分钟就因为 MA5 微拐头被洗出
- 给“突破后首次回踩”更多 5~10 分钟的延续空间

### 九、A/B 回放结果：3/27 明显改善
用更新后的卖出逻辑重新回放 `2026-03-27`，结果从之前的弱表现明显改善为：

#### 调整后回放结果
- `count`: 14
- `win_rate`: 50.0%
- `avg_win_pct`: +0.247%
- `avg_loss_pct`: -0.193%
- `payoff`: 1.28
- `sum_pct`: +0.38%
- `avg_hold_minutes`: 11.6

相对之前观察到的旧结果（约）：
- 胜率：`14.29% -> 50.0%`
- 累计收益：`-0.88% -> +0.38%`
- 平均持有时间显著拉长

这基本支持了今天的判断：
- **问题不只是买点，更主要是卖得太早**
- MA5 拐头在买后 1~3 分钟触发，确实过敏

### 十、已把实盘 YAML 同步到当前有效逻辑
已重写 `skills/fund-monitor/config/default.yaml`，让实盘配置与当前分析验证通过的逻辑保持一致，核心包括：
- `signals.sell.use_ma_turn_exit: true`
- `signals.sell.ma_turn_min_hold_minutes: 6`
- `signals.sell.ma_turn_profit_protect_pct: 0.05`
- `signals.sell.ma_turn_loss_cut_pct: -0.05`
- `signals.sell.ma10_turn_exit_on_loss: true`
- 恢复正常的：
  - `profit_protect_trigger_pct: 0.45`
  - `breakeven_trigger_pct: 0.35`
  - `min_profit_for_ma5_exit_pct: 0.25`
- 补齐 ATR 风控段落

随后已执行：
- `python3 skills/fund-monitor/tools/monitor.py stop`
- `python3 skills/fund-monitor/tools/monitor.py start-bg`
- `python3 skills/fund-monitor/tools/monitor.py status`

结果：
- 配置加载正常
- monitor 已重启并继续运行

### 十一、统一数据口径，补标准统计与简报脚本
为解决外部自动报告反复混用口径的问题，今天新增了：
1. `scripts/fund_monitor_stats.py`
   - 输出结构化 JSON
   - 统一定义：
     - 已完成交易数 = `trades.json` 中 `SELL + CLOSED`
     - 当前持仓数 = `trades.json` 中 `BUY + OPEN`
     - 信号数 = `signals.json` 按 `(type, code, time, reason)` 去重后计数
   - 同时输出：
     - 胜率
     - 收益率盈亏比
     - 金额盈亏比
     - 已实现累计收益率
     - 已实现累计绝对收益
2. `scripts/fund_monitor_brief.py`
   - 基于标准统计脚本输出简版日报 / Markdown 摘要
   - 适合 Telegram / 企业微信 / cron 摘要直接调用
3. `scripts/fund_monitor_export_stats_snapshot.py`
   - 将标准统计结果导出为：
     - `skills/fund-monitor/data/stats_snapshot.json`
   - 方便外部自动任务不必再自己解析 `signals.json/trades.json`

### 十二、补充 README 与数据契约文档
已继续更新：
- `skills/fund-monitor/README.md`
- `skills/fund-monitor/运行数据字段契约说明.md`

新增明确内容包括：
- `signals.json` 是信号事件流，不等于最终交易统计表
- `trades.json` 的推荐统计口径
- 午休时段 `OPEN` 仓位继续保持 `OPEN` 属于预期行为
- 标准统计脚本与标准简报脚本的调用方式

### 十三、当前剩余问题
虽然仓库内已经补齐“标准统计出口”，但外部自动生成的那些监控报告目前**还没有切换到调用标准脚本**，所以你现在仍会看到：
- 有时按 BUY 闭环
- 有时像按 SELL 闭环
- 有时给 `0.40`
- 有时给 `0.20`
- 有时给 `0.38`

也就是说：
- **仓库内标准口径已经做好**
- **外部自动报告链路还没完全接过来**

## 本次涉及文件
1. `skills/fund-monitor/tools/monitor.py`
2. `skills/fund-monitor/README.md`
3. `skills/fund-monitor/tools/signals.py`
4. `skills/fund-monitor/config/default.yaml`
5. `skills/fund-monitor/data/signals.json`
6. `skills/fund-monitor/运行数据字段契约说明.md`
7. `scripts/fund_monitor_stats.py`
8. `scripts/fund_monitor_brief.py`
9. `scripts/fund_monitor_export_stats_snapshot.py`

## 本次本地校验
已执行：
- `python3 -m py_compile skills/fund-monitor/tools/monitor.py`
- `python3 -m py_compile skills/fund-monitor/tools/signals.py`
- `python3 -m py_compile scripts/fund_monitor_stats.py`
- `python3 -m py_compile scripts/fund_monitor_brief.py`
- `python3 scripts/fund_monitor_trade_replay_ab.py --days 2026-03-27`
- `python3 scripts/fund_monitor_stats.py`
- `python3 scripts/fund_monitor_brief.py`
- 配置加载打印检查
- monitor stop/start-bg/status 实盘检查

结果：
- 语法通过
- 3/27 回放在卖出侧优化后明显改善
- 标准统计脚本与简报脚本输出正常
- monitor 重启后正常运行

## 接下来最建议做的事
### 第一优先级：让外部自动报告改为直接消费标准脚本 / 快照
优先不要再让外部任务自己解析：
- `signals.json`
- `trades.json`
- `monitor.log`

而是改为直接读取：
- `python3 scripts/fund_monitor_stats.py`
- 或 `skills/fund-monitor/data/stats_snapshot.json`

### 第二优先级：继续盯 520660 的最终平仓结果
需要继续观察：
- 新配置下，这笔 OPEN 仓最终怎么平
- 是否能验证“卖出不再过早”

### 第三优先级：再做一次更系统的参数扫描
后续可继续对：
- `2026-03-27`
- `2026-03-30`
- 以及后续新样本日

做更系统的对比：
- `ma_turn_min_hold_minutes = 4 / 6 / 8`
- 看胜率、盈亏比、累计收益、平均持仓时长的平衡点

## 一句话总结
今天除了继续补后台启动逻辑外，真正把 fund-monitor 的“最后一公里”基础设施也补上了：
- **修掉了重复 BUY 写入**
- **修正了实盘配置漂移**
- **确认卖出过早是主要问题并做了有效修正**
- **补齐了统一统计口径、标准统计脚本、简版日报脚本、快照导出脚本**

现在仓库内已经具备一个可复用、可审计、可外部消费的标准统计出口；剩下没收口的，主要是：**把外部自动报告链路切到这个新标准上。**
