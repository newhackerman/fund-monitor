"""rotation 包：独立于 T+0 分钟监控的日线 ETF 轮动策略。

预留策略接口设计：
- 每个策略一个独立模块（如 strategy_qixing.py），实现 score_etf / 状态机
- backtest.py 引擎通用，不绑死单一策略
- 后续新增策略（如均线趋势、动量+波动率）只需新增 strategy_xxx.py
"""
