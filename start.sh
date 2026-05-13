#!/usr/bin/env sh
set -e
python3 /app/tools/monitor.py start &
exec python3 /app/tools/webui_server.py
