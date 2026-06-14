#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T+0动量强势策略 —— 日线版（忠实移植自聚宽）

移植来源（聚宽）：
- https://www.joinquant.com/post/72393  在水一方ly
- https://www.joinquant.com/post/70329  king088
- https://www.joinquant.com/post/69163  晨曦量化

移植约定（聚宽 -> 本地）：
- attribute_history(sec, N, '1d', ...) ：取截至"前一日"的 N 根日线（不含当日）
- get_current_data().last_price          ：当日收盘价（日线回测近似）
- run_daily(..., time='13:10')           ：调仓；盈利保护 11:00 检查
                                            日线回测统一在当日收盘前评估、收盘价成交
- g.* 全局变量                           ：打包成 StrategyState 类实例

核心信号链（与聚宽一致）：
  1. 长期动量分 = 加权对数回归斜率年化 × R²
  2. 短期动量过滤（10 日年化 > 阈值）
  3. 近 3 日单日跌幅过滤（< loss_ratio 排除）
  4. 成交量放量过滤（放量 + 高年化排除，防追高末段）
  5. 动态滤波器：正常期=拉普拉斯，震荡期=高斯（需价格在滤波线之上且斜率为正）
  6. 震荡期状态机（基于基准指数的乖离率/RSI/回撤）
  7. 盈利保护：持仓相对前 N 日高点回撤 > 阈值 -> 卖出
  8. 轮动：每日选 score 最高的 holdings_num 只，等权；无目标且防御可用 -> 防御 ETF

本地简化（在报告里标注）：
- 溢价率过滤：本地无基金净值数据源，默认关闭（enable_premium_filter=false）
- 执行价：聚宽用 13:10 实时价，本回测用当日收盘价（日频轮动差异通常 <0.2%）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# 指标原样移植（聚宽 calculate_rsi / laplace_filter / gaussian_filter）
# ============================================================

def calculate_rsi(close: np.ndarray, period: int = 14) -> Optional[float]:
    """聚宽原版 RSI（简单均值法，非 EMA）。返回最后一个值或 None。"""
    try:
        close = np.asarray(close, dtype=float)
        if len(close) < period + 1:
            return None
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
    except Exception:
        return None


def laplace_filter(price: np.ndarray, s: float = 0.05) -> np.ndarray:
    """拉普拉斯滤波（一阶 IIR）。聚宽原版。"""
    alpha = 1 - math.exp(-s)
    n = len(price)
    L = np.zeros(n)
    L[0] = price[0]
    for t in range(1, n):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price: np.ndarray, sigma: float = 1.2) -> tuple[float, float]:
    """高斯滤波，返回最后两根的滤波值（g1=含最后一根，g2=不含最后一根）。聚宽原版。"""
    n = len(price)
    if n < 2:
        return 0.0, 0.0
    idx_1 = np.arange(n)
    w1 = np.exp(-((idx_1 + 1) ** 2) / (2 * sigma ** 2))[::-1]
    w1 /= np.sum(w1)
    g1 = float(np.sum(price * w1))

    price2 = price[:-1]
    idx_2 = np.arange(n - 1)
    w2 = np.exp(-((idx_2 + 1) ** 2) / (2 * sigma ** 2))[::-1]
    w2 /= np.sum(w2)
    g2 = float(np.sum(price2 * w2))
    return g1, g2


def weighted_logreg_annualized(price_series: np.ndarray, lookback_days: int) -> tuple[float, float, float]:
    """加权对数线性回归年化收益 + R² + score。

    聚宽：对近 lookback_days+1 根做 log 回归，权重从 1 线性增至 2，
    斜率年化 = exp(slope*250)-1，score = annualized * r_squared。
    """
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=weights)
    annualized = math.exp(slope * 250) - 1
    ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0.0
    score = annualized * r_squared
    return annualized, r_squared, score


# ============================================================
# 策略状态（对应聚宽 g.* 全局）
# ============================================================

@dataclass
class StrategyState:
    """聚宽 g.* 全局变量的等价物。震荡期状态机依赖它。"""
    current_filter: str = '正常期'      # '正常期' | '震荡期'
    risk_state: str = '正常期'
    previous_rsi: Optional[float] = None
    previous_drawdown: Optional[float] = None
    stable_days: int = 0
    last_switch_date: Optional[pd.Timestamp] = None
    range_bound_start_date: Optional[pd.Timestamp] = None
    range_bound_days_count: int = 0
    stop_loss_triggered_date: Optional[pd.Timestamp] = None


# ============================================================
# 单标的打分（聚宽 calculate_momentum_metrics 的日线版）
# ============================================================

def score_etf(code: str, daily: pd.DataFrame, idx: int, params: dict,
              state: StrategyState, decision_price: Optional[float] = None) -> Optional[dict]:
    """对单只 ETF 在 idx 这一日打分。返回 metrics 或 None（被过滤）。

    idx: 当日下标。
    daily: 完整日线 DataFrame。
    params: 配置 params 段。
    state: 策略状态（用于选择滤波器，但不在本函数内修改）。
    decision_price: 拼到 price_series 末尾的"当日价"。
        - None：用 daily.close[idx]（含未来信息，仅用于对照）
        - 聚宽语义是 13:10 实时价；日线下用前一日收盘价最干净（避免当日全天涨幅泄漏）
    """
    lookback_days = int(params['lookback_days'])
    short_lookback = int(params['short_lookback_days'])

    # 聚宽：prices = attribute_history(etf, lookback, '1d', ['close','high'])
    #        -> 截至"前一日"的日线。current_price = 当日 last_price。
    # 本地：history_end = idx（不含当日），current_price = daily.close[idx]
    need = max(lookback_days, short_lookback) + 25  # 多留余量给滤波器
    if idx < need:
        return None

    hist_close = daily['close'].iloc[:idx].to_numpy(dtype=float)  # 不含当日
    if len(hist_close) < lookback_days + 1:
        return None
    # decision_price：拼到序列末尾的"当日价"。默认用前一日收盘（避免未来信息泄漏）。
    if decision_price is None:
        current_price = float(hist_close[-1]) if len(hist_close) > 0 else float(daily['close'].iloc[idx])
    else:
        current_price = float(decision_price)

    # price_series = np.append(prices['close'].values, current_price)  [聚宽原样]
    price_series = np.append(hist_close, current_price)

    # --- 短期动量过滤 ---
    if params.get('use_short_momentum_filter', True) and len(price_series) >= short_lookback + 1:
        short_ret = price_series[-1] / price_series[-(short_lookback + 1)] - 1
        short_annualized = (1 + short_ret) ** (250 / short_lookback) - 1
    else:
        short_annualized = 0.0
    if params.get('use_short_momentum_filter', True) and short_annualized < params.get('short_momentum_threshold', 0.0):
        return None

    # --- 长期动量 + R² ---
    annualized, r_squared, score = weighted_logreg_annualized(price_series, lookback_days)

    # --- 近 3 日单日跌幅过滤 ---
    if len(price_series) >= 4:
        loss_ratio = float(params.get('loss_ratio', 0.97))
        day1 = price_series[-1] / price_series[-2]
        day2 = price_series[-2] / price_series[-3]
        day3 = price_series[-3] / price_series[-4]
        if min(day1, day2, day3) < loss_ratio:
            return None

    # --- 成交量放量过滤（防追高末段）---
    if params.get('enable_volume_check', True):
        vol_lookback = int(params.get('volume_lookback', 5))
        vol_threshold = float(params.get('volume_threshold', 2))
        vol_return_limit = float(params.get('volume_return_limit', 1.0))
        if idx >= vol_lookback:
            avg_vol = float(daily['volume'].iloc[idx - vol_lookback:idx].mean())
            today_vol = float(daily['volume'].iloc[idx])
            if avg_vol > 0:
                ratio = today_vol / avg_vol
                if ratio > vol_threshold and annualized > vol_return_limit:
                    return None

    # --- 动态滤波器（拉普拉斯 / 高斯）---
    if params.get('enable_range_bound_mode', True) and len(price_series) >= 10:
        laplace_vals = laplace_filter(price_series, s=float(params.get('laplace_s_param', 0.05)))
        laplace_slope = laplace_vals[-1] - laplace_vals[-2] if len(laplace_vals) >= 2 else 0.0
        passed_laplace = (current_price > laplace_vals[-1]
                          and laplace_slope > float(params.get('laplace_min_slope', 0.001)))
        g1, g2 = gaussian_filter_last_two(price_series, sigma=float(params.get('gaussian_sigma', 1.2)))
        gaussian_slope = g1 - g2
        passed_gaussian = (current_price > g1
                           and gaussian_slope > float(params.get('gaussian_min_slope', 0.002)))
        if state.current_filter == '正常期':
            passed_filter = passed_laplace
        else:
            passed_filter = passed_gaussian
        if not passed_filter:
            return None

    # --- 分数阈值 ---
    min_score = float(params.get('min_score_threshold', 0.0))
    max_score = float(params.get('max_score_threshold', 100.0))
    if not (min_score < score < max_score):
        return None

    return {
        'code': code,
        'score': score,
        'annualized': annualized,
        'r_squared': r_squared,
        'current_price': current_price,
        'short_annualized': short_annualized,
    }


# ============================================================
# 震荡期状态机（基于基准指数）
# ============================================================

def get_benchmark_state(bench_daily: pd.DataFrame, idx: int, params: dict) -> Optional[dict]:
    """对应聚宽 get_risk_benchmark_state。返回基准指数的状态。

    日线回测里"当日"= idx。聚宽里 current_price 用当日实时价，
    previous_rsi 用截至前一日算的 RSI。
    """
    ma_period = int(params.get('ma_period', 20))
    hl_days = int(params.get('lookback_high_low_days', 20))
    required = max(ma_period, hl_days) + 5
    if idx < required:
        return None

    close_series = bench_daily['close'].iloc[:idx + 1].to_numpy(dtype=float)  # 含当日
    high_series = bench_daily['high'].iloc[:idx + 1].to_numpy(dtype=float)
    low_series = bench_daily['low'].iloc[:idx + 1].to_numpy(dtype=float)
    current_price = float(close_series[-1])
    recent_high = float(np.max(high_series[-hl_days:]))
    recent_low = float(np.min(low_series[-hl_days:]))
    ma = float(np.mean(close_series[-ma_period:]))
    current_rsi = calculate_rsi(close_series, period=14)
    # previous_rsi = 截至前一日（不含当日）
    previous_rsi = calculate_rsi(close_series[:-1], period=14)
    return {
        'close_series': close_series,
        'current_price': current_price,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'ma': ma,
        'current_rsi': current_rsi,
        'previous_rsi': previous_rsi,
    }


def update_range_bound_state(state: StrategyState, bench_daily: pd.DataFrame,
                             idx: int, params: dict, today: pd.Timestamp) -> None:
    """每日更新震荡期状态机。对应聚宽 check_range_bound（先退出再进入）。

    简化：聚宽在 13:55 跑（调仓 13:10 之后），所以"当日调仓用的是更新前的状态"。
    本回测里我们遵循同样顺序：调仓 -> 更新状态（影响次日）。
    因此本函数应在调仓之后调用。
    """
    if not params.get('enable_range_bound_mode', True):
        return

    bs = get_benchmark_state(bench_daily, idx, params)
    if bs is None:
        return

    bias_threshold = float(params.get('bias_threshold', 0.10))
    rsi_overbought = float(params.get('rsi_overbought', 75))
    rsi_pullback = float(params.get('rsi_pullback', 60))
    low_point_threshold = float(params.get('low_point_rise_threshold', 0.03))
    drawdown_recovery = float(params.get('drawdown_recovery', 0.03))
    max_range_days = int(params.get('max_range_bound_days', 15))
    cooldown = int(params.get('filter_switch_cooldown', 2))

    def _days_since(last_date: Optional[pd.Timestamp]) -> int:
        if last_date is None:
            return 999
        return (today - last_date).days  # 日历日近似（聚宽用交易日，差异可接受）

    # ---------- 退出震荡期检查 ----------
    if state.current_filter == '震荡期':
        close = bs['close_series']
        current_price = bs['current_price']
        recent_high = bs['recent_high']
        recent_low = bs['recent_low']
        current_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0

        recovery_signals = []
        if params.get('enable_low_point_rise_trigger', True) and rise_from_low >= low_point_threshold:
            recovery_signals.append('low_point_rise')
        if params.get('enable_stable_signal_trigger', True):
            if current_price > bs['ma']:
                recovery_signals.append('above_ma')
            if len(close) >= 2 and close[-1] > close[-2]:
                recovery_signals.append('price_up')
            if state.previous_drawdown is not None and current_drawdown < state.previous_drawdown:
                recovery_signals.append('drawdown_narrow')
            if bs['current_rsi'] is not None and state.previous_rsi is not None \
                    and bs['current_rsi'] > state.previous_rsi:
                recovery_signals.append('rsi_up')
            if current_drawdown < drawdown_recovery:
                state.stable_days += 1
            else:
                state.stable_days = 0

        state.previous_drawdown = current_drawdown
        state.previous_rsi = bs['current_rsi']

        range_bound_days = state.range_bound_days_count
        if state.range_bound_start_date is not None:
            range_bound_days = len(bench_daily['close'].iloc[
                bench_daily.index[bench_daily['date'] >= state.range_bound_start_date][0]:idx + 1])
            state.range_bound_days_count = range_bound_days

        low_point_cond = (params.get('enable_low_point_rise_trigger', True)
                          and rise_from_low >= low_point_threshold)
        stable_cond = (params.get('enable_stable_signal_trigger', True)
                       and current_drawdown < drawdown_recovery
                       and len(recovery_signals) >= 2
                       and state.stable_days >= 2)
        force_cond = range_bound_days >= max_range_days

        if (low_point_cond or stable_cond or force_cond) and _days_since(state.last_switch_date) >= cooldown:
            state.current_filter = '正常期'
            state.risk_state = '正常期'
            state.last_switch_date = today
            state.range_bound_start_date = None
            state.range_bound_days_count = 0
            state.stable_days = 0
        return  # 同一日不重复进入

    # ---------- 进入震荡期检查 ----------
    if state.current_filter != '震荡期':
        if _days_since(state.last_switch_date) < cooldown:
            return
        risk_signals = []
        if params.get('enable_bias_trigger', True):
            bias = (bs['current_price'] - bs['ma']) / bs['ma'] if bs['ma'] > 0 else 0
            if bias > bias_threshold:
                risk_signals.append('bias_over')
        if params.get('enable_rsi_trigger', True) and bs['current_rsi'] is not None \
                and bs['previous_rsi'] is not None:
            if (bs['previous_rsi'] > rsi_overbought
                    and bs['current_rsi'] < rsi_pullback
                    and bs['current_rsi'] < bs['previous_rsi']):
                risk_signals.append('rsi_pullback')
        if risk_signals:
            state.current_filter = '震荡期'
            state.risk_state = '震荡期'
            state.last_switch_date = today
            state.range_bound_start_date = today
            state.range_bound_days_count = 0
            state.stable_days = 0


# ============================================================
# 盈利保护
# ============================================================

def check_profit_protection(code: str, daily: pd.DataFrame, idx: int,
                            params: dict, buy_idx: Optional[int] = None) -> bool:
    """盈利保护：当前价相对"基准最高价"回撤超 threshold 触发。

    聚宽原版（profit_protection_lookback=1）：看前 1 日 high。
    但该实现语义上等价于"昨天高点今天回撤"，会误伤刚建仓的标的。
    本回测提供两种模式（params.profit_protection_mode）：
      - 'lookback'（默认，忠实聚宽）：基准 = 前 lookback 日最高价
      - 'since_buy'（推荐）：基准 = 自买入日以来的最高价（真正"保护浮盈"）

    buy_idx: 持仓买入日在 daily 中的下标（since_buy 模式必需）。
    """
    if not params.get('enable_profit_protection', True):
        return False
    threshold = float(params.get('profit_protection_threshold', 0.05))
    mode = str(params.get('profit_protection_mode', 'lookback'))
    current_price = float(daily['close'].iloc[idx])
    if current_price <= 0:
        return False

    if mode == 'since_buy':
        if buy_idx is None or buy_idx < 0:
            return False
        max_high = float(daily['high'].iloc[buy_idx:idx + 1].max())
    else:  # lookback（聚宽原版）
        lookback = int(params.get('profit_protection_lookback', 1))
        if idx < lookback:
            return False
        max_high = float(daily['high'].iloc[idx - lookback:idx].max())

    if max_high <= 0:
        return False
    return current_price <= max_high * (1 - threshold)


# ============================================================
# 实时风控（分钟级，T+0 标的专用）
# ============================================================

def check_realtime_risk_control(holding: dict, current_price: float,
                                params: dict) -> Optional[str]:
    """实时风控检查（分钟级触发，T+0 优势）。

    返回触发的退出原因，None 表示不退出。
    - 硬止损：亏损达 stop_loss_pct 立即卖
    - 止盈保护：浮盈 > profit_protect_activate_pct 后，从 max_price 回撤达
      profit_protect_drawdown_pct 卖出

    holding: {'buy_price', 'max_price', ...} 持仓状态
    current_price: 当前实时价
    params: config['params']（含 realtime_risk_control 子段）
    """
    rrc = params.get('realtime_risk_control') or {}
    if not rrc.get('enabled', True):
        return None

    buy_price = float(holding.get('buy_price', 0))
    if buy_price <= 0:
        return None
    if current_price <= 0:
        return None

    pnl_pct = (current_price - buy_price) / buy_price

    # 1) 硬止损
    stop_loss_pct = float(rrc.get('stop_loss_pct', -0.05))
    if pnl_pct <= stop_loss_pct:
        return f'硬止损({pnl_pct*100:+.1f}%<={stop_loss_pct*100:.0f}%)'

    # 2) 止盈保护（需先达启动门槛）
    activate_pct = float(rrc.get('profit_protect_activate_pct', 0.02))
    max_price = float(holding.get('max_price', buy_price))
    # 更新历史最高价（用于回撤判断）
    if current_price > max_price:
        max_price = current_price

    if max_price > buy_price * (1 + activate_pct):
        # 已达启动门槛，检查回撤
        drawdown_pct = float(rrc.get('profit_protect_drawdown_pct', 0.05))
        drawdown = (max_price - current_price) / max_price
        if drawdown >= drawdown_pct:
            return f'止盈保护(从高点回撤{drawdown*100:.1f}%)'

    return None
