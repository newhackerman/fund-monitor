@echo off
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=0
chcp 65001 >nul

REM 默认分支：使用 Start-Process + pythonw.exe 启动 keepalive 守护。
REM 这样 bat 自己可以很快返回，不会因为控制台关闭把 monitor 一起带掉。
REM 如果只是查询状态/停止/查看日志等，直接透传给 monitor.py。
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONLEGACYWINDOWSSTDIO='0'; Start-Process pythonw.exe -WorkingDirectory '%~dp0' -ArgumentList 'tools\\monitor.py keepalive' -WindowStyle Hidden"
  echo 已发起后台守护启动（Start-Process + pythonw.exe + keepalive）
  echo 建议 3-5 秒后执行：run_monitor_windows.bat status
  echo 如已打开 WebUI，建议先用默认 10s 刷新观察；若机器较慢可切到 20s。
) else (
  python tools\monitor.py %*
)
