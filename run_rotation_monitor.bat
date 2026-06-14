@echo off
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=0
chcp 65001 >nul

REM ETF 轮动 + 风控监控器启动脚本（T+0动量强势策略）
REM 用法：
REM   run_rotation_monitor.bat            后台启动（推荐，常驻）
REM   run_rotation_monitor.bat status     查看状态和当前持仓
REM   run_rotation_monitor.bat stop       停止
REM   run_rotation_monitor.bat run-once   立即跑一次轮动评估（测试，会推送）
REM   run_rotation_monitor.bat dry-run --date 2026-05-15  历史模拟（不推送）

if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONLEGACYWINDOWSSTDIO='0'; Start-Process pythonw.exe -WorkingDirectory '%~dp0' -ArgumentList 'tools\\daily_rotation_monitor.py start-bg' -WindowStyle Hidden"
  echo 已发起后台启动（轮动+风控监控器）
  echo   - 日频轮动：每个交易日 13:10 自动选股
  echo   - 分钟风控：交易时段每 30 秒检查硬止损/止盈保护
  echo 建议 3-5 秒后执行：run_rotation_monitor.bat status
  echo 日志：logs\daily_rotation_monitor.log
) else (
  python tools\daily_rotation_monitor.py %*
)
