# FUND MONITOR PROGRESS - 2026-03-31

## 今天继续推进的内容

### 一、先接上昨天未收口的核心问题：外部自动报告链路仍未切到标准出口
今天先重新读取并核对了：
1. `skills/fund-monitor/FUND_MONITOR_PROGRESS_2026-03-30.md`
2. `scripts/fund_monitor_stats.py`
3. `scripts/fund_monitor_brief.py`
4. `scripts/fund_monitor_export_stats_snapshot.py`
5. `skills/fund-monitor/tools/monitor.py`

昨天已经确认：
- 仓库内的“标准统计口径 / 标准简报 / 标准快照”已经补齐
- 但外部自动报告还在自己读：
  - `monitor.log`
  - `signals.json`
  - `trades.json`
- 所以外部报告仍然会继续出现：
  - 口径漂移
  - 文案过长
  - Telegram 超长报错
  - 有时把旧历史重复讲很长

今天的第一目标，就是把这个链路真正收口。

---

### 二、已定位“外部自动报告”真实入口
今天进一步检查后，已经明确找到外部自动报告任务不是仓库内某个 shell，而是：
- `~/.openclaw/cron/jobs.json`

其中存在一个任务：
- `name: 监控报告`
- `id: 46657a0e-ecf5-435b-aab9-39702a2d3ff9`

它原本的 payload 明确要求 agent：
- 读取 `monitor.log`
- 读取 `signals.json`
- 读取 `trades.json`
- 再自行总结“胜率与盈亏比”

这就解释了为什么昨天虽然标准脚本已经有了，外部报告仍然继续乱口径、长篇化、甚至发出彼此矛盾的数据：
- **因为它根本还没切到标准出口**

这一步把昨天的判断彻底坐实了。

---

### 三、已让 monitor 在运行时自动刷新 `stats_snapshot.json`
今天对：
- `skills/fund-monitor/tools/monitor.py`

做了一个关键补丁，不再依赖手动导出快照。

#### 新增内容
1. 新增脚本路径：
   - `STATS_EXPORT_SCRIPT = /home/node/.openclaw/workspace/scripts/fund_monitor_export_stats_snapshot.py`
2. 新增函数：
   - `export_stats_snapshot()`
3. 在 `run_check()` 里，无论：
   - 本轮有新信号
   - 还是本轮无新信号
   都会执行一次：
   - `export_stats_snapshot()`

#### 这意味着
从今天开始，只要 monitor 正常轮询：
- `skills/fund-monitor/data/stats_snapshot.json`
就会被持续刷新，成为真正可被外部消费的稳定快照，而不是“偶尔手工导出一次”的半成品。

这一步很关键，因为它把“标准统计出口”从**离线脚本**变成了**monitor 主链路的一部分**。

---

### 四、已修改 cron 报告任务，只允许使用标准出口
今天已直接改写：
- `~/.openclaw/cron/jobs.json`

将“监控报告”任务的 prompt 从原来的：
- 自行解析 `monitor.log / signals.json / trades.json`

改为新的明确要求：

#### 只允许使用以下标准出口
1. `scripts/fund_monitor_brief.py`
2. `skills/fund-monitor/data/stats_snapshot.json`

并明确写死：
- **不要再自行解析** `monitor.log` / `signals.json` / `trades.json`
- 如果两者有差异：
  - **以 `fund_monitor_brief.py` 输出为准**

#### 同时增加了输出约束
- 只发**精简版 markdown**
- **不超过 12 行**
- **不要表格**
- **不要长篇分析**
- **不要展开历史排行榜**
- 必须包含：
  - 当前持仓数
  - 已完成交易数
  - 胜率
  - 收益率盈亏比
  - 已实现累计收益率
  - 最新信号
  - 当前持仓（若有）

这一步的直接目标是同时解决两类问题：
1. **统计口径漂移**
2. **Telegram 消息过长导致发送失败**

---

### 五、已重新启动 monitor，使自动快照逻辑正式生效
今天检查时发现当前 monitor 实际是：
- `status = 已停止`

随后已执行：
1. `python3 skills/fund-monitor/tools/monitor.py stop`
2. `python3 skills/fund-monitor/tools/monitor.py start-bg`
3. `python3 skills/fund-monitor/tools/monitor.py status`

结果：
- monitor 已重新后台启动
- 当前 PID：`13488`
- 状态：`🟢 运行中`

这一步的意义在于：
- 让刚刚补进 `monitor.py` 的自动快照刷新逻辑立刻开始生效

---

### 六、今天再次确认当前标准统计结果
今天重新执行并确认：
- `python3 scripts/fund_monitor_export_stats_snapshot.py`
- `python3 scripts/fund_monitor_brief.py`

当前标准口径结果仍为：
- 当前持仓数：`1`
- 已完成交易数：`3`
- 胜率：`33.33%`
- 收益率盈亏比：`0.3784`
- 金额盈亏比：`0.4000`
- 已实现累计收益率：`-0.30%`
- 已实现累计收益：`-0.0040`
- 最新信号：
  - `520660 港股通央企红利ETF南方`
  - `BUY`
  - `2026-03-30 10:32:09`
- 当前持仓：
  - 仍为 `520660`
  - 当前在 `trades.json` 中表现为 `BUY + OPEN`

同时 `status` 也提示：
- 存在 `1` 条跨日 OPEN 仓位

这与昨天记忆、以及今天标准脚本口径是一致的。

---

### 七、今天实际完成的“最后一公里收口”
如果用一句话概括，今天真正完成的是：

#### 昨天是“仓库内已经有标准出口”
而今天是：
#### **把外部自动报告真正接到了这个标准出口上**

具体来说，今天把三层链路打通了：

1. **monitor 主循环**
   - 自动刷新 `stats_snapshot.json`
2. **标准脚本层**
   - `fund_monitor_brief.py` 作为主口径
3. **外部 cron 报告任务**
   - 改为只消费标准脚本 / 标准快照

这意味着从今天开始，fund-monitor 的自动报告理论上应该：
- 不再反复长篇读取原始日志
- 不再继续自己发明统计口径
- 不再轻易出现 Telegram 超长报错
- 不再和仓库内标准结果打架

当然，这还需要等 cron 下一轮真实执行去验证最终效果。

---

## 今天涉及文件
1. `skills/fund-monitor/tools/monitor.py`
2. `~/.openclaw/cron/jobs.json`
3. `skills/fund-monitor/FUND_MONITOR_PROGRESS_2026-03-31.md`

---

## 今天本地校验
已执行：
- `python3 -m py_compile skills/fund-monitor/tools/monitor.py`
- `python3 scripts/fund_monitor_export_stats_snapshot.py`
- `python3 scripts/fund_monitor_brief.py`
- `python3 skills/fund-monitor/tools/monitor.py status`
- `python3 skills/fund-monitor/tools/monitor.py stop`
- `python3 skills/fund-monitor/tools/monitor.py start-bg`
- `python3 skills/fund-monitor/tools/monitor.py status`

结果：
- monitor.py 语法通过
- 标准快照导出正常
- 标准简报输出正常
- monitor 已重新启动并处于运行中
- 自动快照刷新逻辑已随 monitor 重启进入生效状态

---

## 当前剩余问题
### 1. cron 新 prompt 是否会按预期输出“超短标准简报”
今天虽然已经改了 `jobs.json`，但仍需要观察 cron 下一轮真实运行时是否：
- 真正遵守“只用标准出口”
- 真正遵守“不超过 12 行”
- 不再输出表格
- 不再出现 Telegram 超长失败

### 2. `signals.json` / `trades.json` 状态不同步问题仍然存在一部分历史残留风险
今天重点处理的是**报告链路**，不是信号状态同步本身。
如果后面还看到：
- `signals.json` 某些 BUY 仍显示 OPEN
- 但 `trades.json` 已 CLOSED

那就需要再单独继续修 `signals.py` 或信号回写逻辑。

### 3. 跨日 OPEN 仓位仍需继续盯
当前 monitor status 仍提示：
- `1` 条跨日 OPEN 仓位

这代表：
- 当前数据层面依然需要继续确认这笔 `520660` 最终应如何处理

---

## 接下来最建议做的事
### 第一优先级：观察 cron 下一轮真实输出
重点看三件事：
1. 是否只引用标准简报 / 快照
2. 是否不再出现口径漂移
3. 是否不再出现 Telegram `message is too long`

### 第二优先级：如果外部输出仍超长，就进一步把 `fund_monitor_brief.py` 拆成 ultra-brief
也就是说，不是让 agent“自己概括”，而是直接提供一个更短的：
- `fund_monitor_ultra_brief.py`

让 cron 彻底只转发 6~10 行固定模板。

### 第三优先级：后续再继续处理信号状态同步
等报告链路稳定后，再回头继续清：
- `signals.json` 的 OPEN/CLOSE 残留状态
- 让 `signals` 与 `trades` 语义进一步对齐

---

## 一句话总结
今天把 fund-monitor 昨天剩下的“最后一公里”真正收口了：
- **找到了外部自动报告的真实入口（cron job）**
- **让 monitor 自动刷新 `stats_snapshot.json`**
- **把 cron 报告任务切到了标准脚本 / 标准快照**
- **同时把自动报告约束成短报文，准备解决 Telegram 超长失败**

也就是说：
### fund-monitor 现在不只是“仓库里有标准口径”，而是“外部自动报告链路也开始真正接标准口径了”。


---

## 12:09 之后的紧急修正（按用户明确规则回滚卖出逻辑）

用户明确指出，当前代码中的卖出逻辑与他先前口头定义的规则完全不一致。
经重新确认，用户要求的规则为：
1. 开仓后盈利 `5%` 强制止盈
2. 开仓后亏损 `1%` 强制止损
3. 一旦出现过盈利，从最高浮盈回撤 `1%` 强制平仓
4. 其他情况，持仓超过 `20` 分钟强制平仓
5. 当日未平仓需要持续跟踪，且不允许跨日挂死

### 已执行修正
#### 1. 直接重写 `signals.py` 的卖出逻辑
已将原先偏技术指标驱动的卖出逻辑移除出主链：
- MA5 拐头止盈 / 止损
- MA10 转弱保护
- ATR 动态止损 / 止盈
- 保本回撤保护
- 盈利保护触发
- 尾盘风险收敛 / 尾盘强平

当前 `detect_sell_signal()` 已收敛为用户指定的 4 条规则：
- 固定止盈 `5%`
- 固定止损 `-1%`
- 最高浮盈回撤 `1%`
- 持仓超过 `20` 分钟强制平仓

同时补充：
- `allow_overnight: false` 时，如果发现跨日 OPEN 仓，直接触发：
  - `跨日补救强制平仓`

#### 2. 新增持仓内的最高浮盈跟踪字段
为了实现“有盈利后，盈利回撤 1% 强制平仓”，已在交易记录中加入：
- `max_profit_pct`

处理方式：
- BUY 建仓时初始化为 `0.0`
- 每轮 `generate_signals()` 若发现当前浮盈高于历史最高浮盈，则更新该字段
- 卖出时按：
  - `max_profit_pct - current_profit_pct >= 1.0`
  触发平仓

#### 3. 已同步重写 `config/default.yaml` 中的 sell 段
当前实际生效的卖出配置已被改为：
- `take_profit_pct: 5.0`
- `stop_loss_pct: 1.0`
- `trailing_drawdown_pct: 1.0`
- `max_hold_minutes: 20`
- `allow_overnight: false`

其余原先那套复杂卖出参数已不再作为主逻辑生效。

### 已验证：520660 在新规则下不会再无限挂着
使用 `520660_2026-03-30` 的分钟数据按新逻辑重放后，最早触发时间为：
- `2026-03-30 10:53:00`
- 原因：
  - `超时强制平仓 (20.9 分钟 >= 20.0 分钟)`

这说明：
- 按用户规则，这笔单最迟应在买入约 21 分钟后平掉
- 不会继续挂到下午，更不会跨日继续挂 OPEN

### 当前判断
这一步不是微调，而是一次明确“回滚到用户指定规则”的修正。
现在主链卖出逻辑终于重新与用户口头定义对齐。
后续还需要继续观察两点：
1. live monitor 在盘中是否确实按这套新规则落地出 SELL
2. 对于已存在的跨日 OPEN 仓，补救强平是否在下一轮盘中检查中正确执行


### 继续收口：异常 OPEN 仓告警与旧仓兼容
- 再次核对当前主卖出规则已与用户定义一致：
  - 固定止盈 5%
  - 固定止损 -1%
  - 最高浮盈回撤 1%
  - 持仓超过 20 分钟强制平仓
- 核对 `default.yaml` 已同步上述配置
- 发现历史 `trades.json` 中遗留的 `520660` OPEN 仓没有 `max_profit_pct` 字段，因此补写兼容字段，避免旧仓进入新规则时缺少追踪字段
- 修改 `scripts/fund_monitor_brief.py`：若存在跨日 OPEN 仓，则优先输出“跨日异常持仓告警”，不再像正常 OPEN 一样反复平铺展示
