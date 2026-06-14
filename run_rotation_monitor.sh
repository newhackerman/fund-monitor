#!/usr/bin/env bash
# ETF 轮动 + 风控监控器启动脚本（Linux/macOS，T+0动量强势策略）
#
# 用法：
#   ./run_rotation_monitor.sh               后台启动（推荐，常驻）
#   ./run_rotation_monitor.sh status        查看状态和当前持仓
#   ./run_rotation_monitor.sh stop          停止
#   ./run_rotation_monitor.sh run-once      立即跑一次轮动评估（测试，会推送）
#   ./run_rotation_monitor.sh dry-run --date 2026-05-15   历史模拟（不推送）
#   ./run_rotation_monitor.sh foreground    前台运行（日志直接输出，调试用）
#
# 跨平台：脚本自动定位项目根目录，可在任意位置执行。
set -e

# 定位项目根目录（脚本所在目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 选择 python（优先 python3）
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "❌ 未找到 python/python3，请先安装" >&2
    exit 1
fi

MONITOR="tools/daily_rotation_monitor.py"

# 无参数：后台启动
if [ $# -eq 0 ]; then
    exec $PY "$MONITOR" start-bg
fi

# 透传其他子命令
case "$1" in
    foreground)
        # 前台运行（调试用，Ctrl+C 退出）
        exec $PY "$MONITOR" run-loop
        ;;
    *)
        exec $PY "$MONITOR" "$@"
        ;;
esac
