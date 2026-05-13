# FUND MONITOR PROGRESS - 2026-03-29

## 今天完成的核心工作

### 一、GitHub 仓库整理与发布
1. 重新梳理了 `skills/fund-monitor/` 下需要进入仓库的项目文件。
2. 补齐并推送了 fund-monitor 相关脚本与分析文档。
3. 明确排除了不属于 fund-monitor 的内容，以及安装包等无关文件。
4. 已创建并推送版本标签：
   - `v0.1.0`
5. 用户已手动完成 GitHub Release 发布。

### 二、Web UI 语义与统计口径修正
1. 已把 Web UI 中：
   - `BUY / SELL`
   - `OPEN / CLOSED`
   的混合语义拆开。
2. 当前页面已拆成：
   - **交易事件流**
   - **当前未平仓持仓**
3. 修正了“运行状态已停止但仍显示 PID”的展示逻辑：
   - 进程停止时 `pid` 不再直接显示旧值。
4. 修正了顶部概览统计口径：
   - 当前策略按 **只做多** 处理
   - `交易数` 按 `BUY` 笔数统计
   - 应满足：
     - `交易数 = 平仓数 + 未平仓`
5. 修正了持仓判定逻辑：
   - 不再机械依赖 `BUY + OPEN`
   - 改为按 `BUY.id` 与 `SELL.linked_buy_id` 判断闭环

### 三、monitor 运行与兼容性修正
1. 检查并启动了 fund-monitor monitor。
2. 在 Linux/OpenClaw 环境中 monitor 可正常启动、正常调度。
3. 针对 Windows 本地部署场景，已改 `monitor.py`：
   - `start-bg` 单独走 Windows detached/process group 逻辑
   - 增加 `stdin=DEVNULL`
   - `BackgroundScheduler(daemon=False)`
4. 但 **Windows 本地下 `start-bg` 是否稳定常驻，仍需继续验证**。
   - 目前现象是：
     - monitor 能启动
     - 但后台常驻稳定性仍可能有问题

### 四、数据文件与仓库现状
1. 已按用户明确要求，将这两个运行数据文件提交到 GitHub：
   - `skills/fund-monitor/data/signals.json`
   - `skills/fund-monitor/data/trades.json`
2. `skills/fund-monitor/` 下项目主文件、说明文档、配置、Web UI、脚本基本都已进入仓库。
3. 当前仍不建议把这些运行产物继续纳入仓库：
   - `logs/`
   - `minute_cache/`
   - `minute_cache_quality/`
   - `monitor.pid`
   - `__pycache__/`
   - `.pyc`

## 今天关键提交（按时间线）
- `7c73ad2` refactor fund-monitor webui event flow and position view
- `08422d4` add ta-lib dependency for fund-monitor
- `5efe6bc` track fund-monitor signals and trades data
- `5eb9bab` fix monitor startup and webui position status logic
- `1a05694` align long-only trade count in webui summary
- `89ba322` fix webui server syntax and long-only summary logic
- `a9b7533` sync fund-monitor project files scripts and analysis docs
- `15d90c6` add release notes for v0.1.0
- tag: `v0.1.0`

## 明天继续的优先级

### 第一优先级：Windows 后台常驻问题
重点继续查：
- 为什么用户本地 Windows / PowerShell 下：
  - `python monitor.py start`
  - `python monitor.py start-bg`
  启动后仍可能自动退出
- 优先检查：
  - 是否需要更稳的 Windows 后台进程方案
  - 是否要改为 `pythonw` / 独立窗口 / 计划任务 / 服务化
  - 是否还有父进程会话绑定问题

### 第二优先级：仓库收尾
可继续做：
- 清理 `__pycache__` / `.pyc`
- 补强 `.gitignore`
- 再检查一遍 release 后仓库是否还有不该保留的杂项

### 第三优先级：策略主线
UI、发布、仓库整理基本告一段落后，回到真正主问题：
- **触发买点后的质量不稳定**
- 继续比较：
  - 3/25 的盈利样本
  - 3/27 的亏损样本
- 继续拆：
  - breakout_pullback 条件是否仍偏宽
  - MA5 拐头卖出是否过早
  - 入场后 3~10 分钟动能是否不足

## 明天最先打开的文件
1. `skills/fund-monitor/tools/monitor.py`
2. `skills/fund-monitor/tools/webui_server.py`
3. `skills/fund-monitor/tools/webui/index.html`
4. `skills/fund-monitor/README.md`
5. 这个文件：`skills/fund-monitor/FUND_MONITOR_PROGRESS_2026-03-29.md`

## 一句话总结
今天已经把 **fund-monitor 的仓库整理、Web UI 口径修正、release 发布、数据文件入库、monitor/Windows 兼容性修正** 推进完一轮；明天最该继续的是：**把 Windows 下 monitor 后台常驻问题彻底查清，并回到“买点质量不稳定”的策略优化主线。**
