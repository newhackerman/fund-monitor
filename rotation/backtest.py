#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线回测引擎 —— T+0动量强势策略

执行流程（对应聚宽调度）：
  每个交易日（收盘前评估，收盘价成交）：
    1. 盈利保护检查（持仓相对前 N 日高点回撤 -> 卖出）   [聚宽 11:00]
    2. 给池中所有 ETF 打分，选 top-N                      [聚宽 13:10 调仓]
    3. 卖出不在目标列表的持仓
    4. 买入目标 ETF（等权），无目标且防御可用 -> 防御 ETF
    5. 更新震荡期状态机（影响次日滤波器选择）             [聚宽 13:55]

成交约束（与聚宽对齐）：
- T+1：当日买入的份额次日才能卖出（持仓记录 available_date）
- 等权：每只目标 ETF 目标市值 = 总市值 / holdings_num
- 涨跌停：日线回测无法精确判断，用当日 close vs prev_close * 1.1/0.9 近似
- 交易成本：双边 commission_rate，最低 min_commission；滑点 slippage
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .strategy_momentum import (
    StrategyState,
    check_profit_protection,
    score_etf,
    update_range_bound_state,
)


@dataclass
class Position:
    code: str
    shares: int
    cost_price: float          # 持仓成本（含费用）
    available_date: pd.Timestamp  # T+1：可卖日期（买入次日）
    buy_price: float           # 买入价（不含费用，用于复盘）
    buy_idx: int               # 买入日在该标的数据中的下标（盈利保护 since_buy 模式用）


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame      # date, equity, benchmark, cash
    trades: list[dict]              # 每笔交易明细
    holdings_log: list[dict]        # 每日持仓快照
    metrics: dict                   # 汇总指标
    range_bound_log: list[dict]     # 震荡期切换记录


# ============================================================
# 工具
# ============================================================

def _is_limit_up(code: str, daily: pd.DataFrame, idx: int) -> bool:
    """近似涨停：当日收盘 >= 前收 * 1.099（ETF 涨停 10%）。买入时跳过。"""
    if idx <= 0:
        return False
    prev = float(daily['close'].iloc[idx - 1])
    cur = float(daily['close'].iloc[idx])
    if prev <= 0:
        return False
    return cur >= prev * 1.099


def _is_limit_down(code: str, daily: pd.DataFrame, idx: int) -> bool:
    if idx <= 0:
        return False
    prev = float(daily['close'].iloc[idx - 1])
    cur = float(daily['close'].iloc[idx])
    if prev <= 0:
        return False
    return cur <= prev * 0.901


def _apply_cost(turnover: float, commission_rate: float, min_commission: float) -> float:
    """计算单边交易成本。"""
    return max(turnover * commission_rate, min_commission)


# ============================================================
# 回测主循环
# ============================================================

def run_backtest(data: dict[str, pd.DataFrame], bench_daily: pd.DataFrame,
                 etf_pool: list[str], defensive_etf: str, params: dict,
                 bt_cfg: dict) -> BacktestResult:
    """运行回测。

    data: {code: daily_df}，已对齐日期。
    bench_daily: 基准指数日线。
    etf_pool: 候选 ETF 代码列表。
    defensive_etf: 防御 ETF 代码。
    params: 策略参数（rotation.yaml 的 params 段）。
    bt_cfg: 回测参数（rotation.yaml 的 backtest 段）。
    """
    # ---------- 准备 ----------
    start = pd.Timestamp(bt_cfg['start'])
    end = pd.Timestamp(bt_cfg['end'])
    initial_capital = float(bt_cfg['initial_capital'])
    commission_rate = float(bt_cfg.get('commission_rate', 0.0001))
    min_commission = float(bt_cfg.get('min_commission', 5.0))
    slippage = float(bt_cfg.get('slippage', 0.0001))
    holdings_num = int(params.get('holdings_num', 1))
    # T+0：当日买入当日可卖（跨境/黄金/债券/货币ETF）；T+1：次日才能卖
    t_plus_zero = bool(params.get('t_plus_zero', False))
    # 防御 ETF 可能为 None（池内无货币/债券类时）
    has_defensive = defensive_etf is not None and defensive_etf in data

    # 用所有标的日期的并集作为交易日历
    all_dates = sorted(set().union(*[set(d['date']) for d in data.values() if not d.empty]))
    trade_dates = [d for d in all_dates if start <= d <= end]
    if not trade_dates:
        raise ValueError(f'回测区间 [{start}~{end}] 内无交易日')

    # 按 date 建索引，便于 O(1) 查 idx
    date_idx: dict[str, dict[pd.Timestamp, int]] = {}
    for code, df in data.items():
        m = {ts: i for i, ts in enumerate(df['date'])}
        date_idx[code] = m

    bench_date_idx = {ts: i for i, ts in enumerate(bench_daily['date'])} if not bench_daily.empty else {}

    # ---------- 状态 ----------
    cash = initial_capital
    positions: list[Position] = []
    state = StrategyState()
    trades: list[dict] = []
    holdings_log: list[dict] = []
    range_bound_log: list[dict] = []
    equity_curve_rows: list[dict] = []
    prev_filter = state.current_filter

    # ---------- 主循环 ----------
    for today in trade_dates:
        # 当日各标的的 idx（若当日无数据则取最近前一根）
        def _idx_of(code: str, t: pd.Timestamp) -> int:
            m = date_idx.get(code, {})
            if t in m:
                return m[t]
            # 回退到 <= t 的最近一根
            cand = [d for d in m if d <= t]
            return m[max(cand)] if cand else -1

        # ---------- 1. 盈利保护检查（仅对持仓，且须满足可卖条件）----------
        for pos in positions[:]:
            if not t_plus_zero and pos.available_date > today:
                continue  # T+1 规则下，买入次日才能卖
            idx = _idx_of(pos.code, today)
            if idx < 0:
                continue
            df = data[pos.code]
            if check_profit_protection(pos.code, df, idx, params, buy_idx=pos.buy_idx):
                price = float(df['close'].iloc[idx])
                if _is_limit_down(pos.code, df, idx):
                    continue  # 跌停卖不出
                sell_price = price * (1 - slippage)
                turnover = pos.shares * sell_price
                cost = _apply_cost(turnover, commission_rate, min_commission)
                cash += turnover - cost
                trades.append({
                    'date': today, 'code': pos.code, 'action': 'SELL',
                    'reason': 'profit_protection',
                    'shares': pos.shares, 'price': round(sell_price, 4),
                    'cost': round(cost, 2),
                    'pnl': round((sell_price - pos.cost_price) * pos.shares - cost, 2),
                    'pnl_pct': round((sell_price / pos.cost_price - 1) * 100, 2)
                        if pos.cost_price > 0 else 0.0,
                })
                positions.remove(pos)

        # ---------- 2. 打分 + 选目标 ----------
        scored: list[dict] = []
        for code in etf_pool:
            if code not in data:
                continue
            idx = _idx_of(code, today)
            if idx < 0:
                continue
            # 涨停不买
            if _is_limit_up(code, data[code], idx):
                continue
            # 决策价 = 当日收盘价（与成交价一致，日线回测标准做法，无未来信息泄漏）
            # 注：聚宽原策略 13:10 用实时价，日线回测用收盘价近似；实盘需考虑 13:10→收盘的滑点
            m = score_etf(code, data[code], idx, params, state,
                          decision_price=float(data[code]['close'].iloc[idx]))
            if m is not None:
                scored.append(m)
        scored.sort(key=lambda x: x['score'], reverse=True)
        target_codes = [m['code'] for m in scored[:holdings_num]]

        # 无目标 -> 防御 ETF（池内无防御标的时直接空仓）
        defensive_available = False
        if has_defensive:
            di = _idx_of(defensive_etf, today)
            if di >= 0 and not _is_limit_up(defensive_etf, data[defensive_etf], di):
                defensive_available = True
        if not target_codes and defensive_available:
            target_codes = [defensive_etf]

        # ---------- 3. 卖出不在目标的持仓 ----------
        target_set = set(target_codes)
        for pos in positions[:]:
            if pos.code in target_set:
                continue
            if not t_plus_zero and pos.available_date > today:
                continue  # T+1 规则下，买入次日才能卖
            idx = _idx_of(pos.code, today)
            if idx < 0:
                continue
            df = data[pos.code]
            if _is_limit_down(pos.code, df, idx):
                continue
            price = float(df['close'].iloc[idx])
            sell_price = price * (1 - slippage)
            turnover = pos.shares * sell_price
            cost = _apply_cost(turnover, commission_rate, min_commission)
            cash += turnover - cost
            trades.append({
                'date': today, 'code': pos.code, 'action': 'SELL',
                'reason': 'rotation_out',
                'shares': pos.shares, 'price': round(sell_price, 4),
                'cost': round(cost, 2),
                'pnl': round((sell_price - pos.cost_price) * pos.shares - cost, 2),
                'pnl_pct': round((sell_price / pos.cost_price - 1) * 100, 2)
                    if pos.cost_price > 0 else 0.0,
            })
            positions.remove(pos)

        # ---------- 4. 买入目标（等权）----------
        total_equity = cash + sum(
            p.shares * float(data[p.code]['close'].iloc[_idx_of(p.code, today)])
            for p in positions if _idx_of(p.code, today) >= 0
        )
        if target_codes:
            target_per = total_equity / len(target_codes)
            for code in target_codes:
                if code not in data:
                    continue
                idx = _idx_of(code, today)
                if idx < 0:
                    continue
                # 已持有则跳过（聚宽：偏差 < 5% 不调）
                already = next((p for p in positions if p.code == code), None)
                if already:
                    continue
                if _is_limit_up(code, data[code], idx):
                    continue
                price = float(data[code]['close'].iloc[idx])
                buy_price = price * (1 + slippage)
                target_shares = int(target_per / buy_price / 100) * 100  # 按 100 股取整
                if target_shares <= 0:
                    continue
                turnover = target_shares * buy_price
                cost = _apply_cost(turnover, commission_rate, min_commission)
                if cash < turnover + cost:
                    target_shares = int((cash - cost) / buy_price / 100) * 100
                    if target_shares <= 0:
                        continue
                    turnover = target_shares * buy_price
                    cost = _apply_cost(turnover, commission_rate, min_commission)
                cash -= turnover + cost
                # 成本价 = (turnover+cost)/shares
                cost_price = (turnover + cost) / target_shares
                positions.append(Position(
                    code=code, shares=target_shares, cost_price=cost_price,
                    available_date=today + pd.Timedelta(days=1),  # T+1
                    buy_price=buy_price,
                    buy_idx=idx,
                ))
                trades.append({
                    'date': today, 'code': code, 'action': 'BUY',
                    'reason': 'rotation_in' if code != defensive_etf else 'defensive',
                    'shares': target_shares, 'price': round(buy_price, 4),
                    'cost': round(cost, 2), 'pnl': 0.0, 'pnl_pct': 0.0,
                })

        # ---------- 5. 记录净值 ----------
        holdings_value = sum(
            p.shares * float(data[p.code]['close'].iloc[_idx_of(p.code, today)])
            for p in positions if _idx_of(p.code, today) >= 0
        )
        equity = cash + holdings_value
        bench_idx = bench_date_idx.get(today, -1)
        bench_price = float(bench_daily['close'].iloc[bench_idx]) if bench_idx >= 0 else np.nan
        equity_curve_rows.append({
            'date': today, 'equity': round(equity, 2), 'cash': round(cash, 2),
            'holdings_value': round(holdings_value, 2),
            'benchmark': round(bench_price, 4),
        })

        holdings_log.append({
            'date': today,
            'holdings': [{'code': p.code, 'shares': p.shares,
                          'cost': round(p.cost_price, 4)} for p in positions],
            'n_holdings': len(positions),
        })

        # ---------- 6. 更新震荡期状态机 ----------
        prev = state.current_filter
        bi = bench_date_idx.get(today, -1)
        if bi >= 0:
            update_range_bound_state(state, bench_daily, bi, params, today)
        if state.current_filter != prev:
            range_bound_log.append({
                'date': today, 'from': prev, 'to': state.current_filter,
            })

    # ---------- 结果 ----------
    equity_curve = pd.DataFrame(equity_curve_rows)
    result = BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        holdings_log=holdings_log,
        metrics=_compute_metrics(equity_curve, trades, initial_capital, bench_daily),
        range_bound_log=range_bound_log,
    )
    return result


# ============================================================
# 指标计算
# ============================================================

def _compute_metrics(equity_curve: pd.DataFrame, trades: list[dict],
                     initial_capital: float, bench_daily: pd.DataFrame) -> dict:
    """计算收益/回撤/胜率/换手等汇总指标。"""
    if equity_curve.empty:
        return {}

    eq = equity_curve['equity'].to_numpy(dtype=float)
    dates = equity_curve['date'].to_numpy()

    total_return = eq[-1] / initial_capital - 1
    n_days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    annual_return = (eq[-1] / initial_capital) ** (365.0 / max(n_days, 1)) - 1 if n_days > 0 else 0

    # 最大回撤
    running_max = np.maximum.accumulate(eq)
    drawdown = (eq - running_max) / running_max
    max_drawdown = float(drawdown.min())

    # 日收益率 -> 夏普（年化，无风险 0）
    daily_ret = pd.Series(eq).pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * math.sqrt(252)) if daily_ret.std() > 0 else 0.0
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0

    # 交易统计（仅看 SELL 的 pnl）
    sells = [t for t in trades if t['action'] == 'SELL']
    wins = [t for t in sells if t['pnl'] > 0]
    losses = [t for t in sells if t['pnl'] < 0]
    win_rate = len(wins) / len(sells) if sells else 0.0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0.0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0.0
    profit_factor = (sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))
                     if losses and sum(t['pnl'] for t in losses) != 0 else
                     (float('inf') if wins else 0.0))

    # 换手（买入笔数 / 交易日数）
    n_buys = len([t for t in trades if t['action'] == 'BUY'])
    n_trade_days = len(equity_curve)
    turnover_per_day = n_buys / n_trade_days if n_trade_days else 0

    # 基准收益
    bench_ret = float('nan')
    if not equity_curve.empty and 'benchmark' in equity_curve:
        b = equity_curve['benchmark'].dropna()
        if len(b) >= 2:
            bench_ret = b.iloc[-1] / b.iloc[0] - 1

    # 震荡期占比（持仓在防御 ETF 的天数比）
    return {
        'start_date': str(pd.Timestamp(dates[0]).date()),
        'end_date': str(pd.Timestamp(dates[-1]).date()),
        'n_trade_days': n_trade_days,
        'initial_capital': initial_capital,
        'final_equity': round(eq[-1], 2),
        'total_return_pct': round(total_return * 100, 2),
        'annual_return_pct': round(annual_return * 100, 2),
        'max_drawdown_pct': round(max_drawdown * 100, 2),
        'sharpe': round(sharpe, 3),
        'calmar': round(calmar, 3),
        'n_trades': len(trades),
        'n_sells': len(sells),
        'n_buys': n_buys,
        'win_rate_pct': round(win_rate * 100, 2),
        'avg_win_pct': round(avg_win, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
        'turnover_per_day': round(turnover_per_day, 3),
        'benchmark_return_pct': round(bench_ret * 100, 2) if not math.isnan(bench_ret) else None,
        'excess_return_pct': round((total_return - bench_ret) * 100, 2)
            if not math.isnan(bench_ret) else None,
    }
