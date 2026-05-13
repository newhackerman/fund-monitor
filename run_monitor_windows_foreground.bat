@echo off
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=0
chcp 65001 >nul
python tools\monitor.py start
