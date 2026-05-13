# Windows UTF-8 兼容说明

为避免 Windows 默认 GBK 控制台导致 `UnicodeEncodeError`，fund-monitor 现已补充以下兼容措施：

## 程序内兼容
`tools/monitor.py` 启动时会自动：
- 设置 `PYTHONUTF8=1`
- 设置 `PYTHONIOENCODING=utf-8`
- 设置 `PYTHONLEGACYWINDOWSSTDIO=0`
- Windows 下尝试执行 `chcp 65001`
- 将 `stdout/stderr` 重设为 `utf-8`

## 推荐启动方式
在 Windows 下优先使用：

```bat
run_monitor_windows.bat
run_monitor_windows.bat status
run_monitor_windows.bat stop
```

默认直接执行 `run_monitor_windows.bat` 时，会通过 `PowerShell Start-Process + pythonw.exe` 发起后台守护启动，实际执行 `keepalive` 模式。

如果你需要前台盯日志运行，使用：

```bat
run_monitor_windows_foreground.bat
```

前台脚本会先切到 UTF-8 环境，再调用：

```bat
python tools\monitor.py start
```

## keepalive 守护模式
新增命令：

```bat
python tools\monitor.py keepalive
```

作用：
- 由一个外层守护进程拉起真正的 `start --skip-warmup` 子进程
- 如果子进程异常退出，5 秒后自动重启
- 适合 Windows 上偶发 `pythonw.exe` 子进程消失的场景

## 后台启动补充说明
- 后台默认附带 `--skip-warmup`，避免启动阶段 37 只基金预热过慢
- 默认后台拉起优先走 Windows 原生 `Start-Process`
- 默认后台入口已切到 `keepalive`，降低单个监控进程意外退出后的中断风险
- 若需要验证是否真的常驻，先执行 `run_monitor_windows.bat`，再执行 `run_monitor_windows.bat status`

## 新的后台诊断链路
Windows 后台启动现在新增两类运行标记：
- `logs/monitor_startup.log`：记录后台拉起、命令行、scheduler 启动、PID 写入、进入主循环、异常/退出、keepalive 重启记录
- `data/monitor_heartbeat.json`：记录 `pid / status / phase / time / ts`

推荐排查顺序：
1. `run_monitor_windows.bat`
2. 等 3-5 秒后执行 `run_monitor_windows.bat status`
3. 查看 `logs/monitor_startup.log`
4. 查看 `data/monitor_heartbeat.json`
5. 再看 `logs/monitor.log` / `logs/monitor_stdout.log`

## 如果仍然被系统环境杀掉
若某些机器上连 `Start-Process + pythonw.exe + keepalive` 仍被安全软件、策略或会话环境影响，建议直接切到 Windows 任务计划程序常驻。这不是降级，而是 Windows 上更原生的守护方式。
