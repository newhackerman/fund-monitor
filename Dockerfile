FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    ca-certificates \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/data /app/logs /app/config /app/tools/webui

# 启动 ETF 轮动 + 风控监控器（聚宽七星高照策略移植版）
# - 日频轮动：每个交易日 13:10 自动选股
# - 分钟风控：交易时段每 30 秒检查硬止损/止盈保护
# - 信号推送到企业微信（config/rotation.yaml 配置）
#
# 数据/配置/日志通过 docker-compose 挂载卷持久化，容器重启不丢持仓状态。
#
# 如需同时启用旧 webui（端口 8787），取消下一行注释，并把 CMD 改为：
#   CMD ["/bin/sh","-c","python3 /app/tools/daily_rotation_monitor.py run-loop & python3 /app/tools/webui_server.py"]
# EXPOSE 8787

CMD ["python3", "/app/tools/daily_rotation_monitor.py", "run-loop"]
