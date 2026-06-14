"""rotation 包：T+0动量强势策略核心 + 日线回测。

预留策略接口设计：
- 每个策略一个独立模块（如 strategy_momentum.py），实现 score_etf / 状态机
- backtest.py 引擎通用，不绑死单一策略
- 后续新增策略（如均线趋势、动量+波动率）只需新增 strategy_xxx.py
"""
