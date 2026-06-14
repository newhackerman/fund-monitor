#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号生成引擎 - 主逻辑切换为突破后首次回踩"""

from datetime import datetime
from typing import List
import json
import os

TRADES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'trades.json')
SIGNALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'signals.json')


def check_death_cross(current: float, prev: float, dea_current: float, dea_prev: float) -> bool:
    return prev >= dea_prev and current < dea_current


def load_trades() -> list:
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_trades(trades: list):
    trades = trades[-200:]
    with open(TRADES_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


def find_open_position(code: str, trades: list) -> dict:
    for trade in reversed(trades):
        if trade['code'] == code and trade['type'] == 'BUY' and trade['status'] == 'OPEN':
            return trade
    return None


def calculate_profit(buy_price: float, sell_price: float) -> dict:
    profit = sell_price - buy_price
    profit_pct = (profit / buy_price) * 100 if buy_price > 0 else 0
    return {'profit': round(profit, 4), 'profit_pct': round(profit_pct, 2)}


def _parse_time(ts: str):
    try:
        return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _recent_same_signal(code: str, signal_type: str, cooldown_minutes: int, trades: list) -> bool:
    if cooldown_minutes <= 0:
        return False
    for trade in reversed(trades):
        if trade.get('code') != code or trade.get('type') != signal_type:
            continue
        dt = _parse_time(trade.get('time', ''))
        if not dt:
            continue
        mins = (datetime.now() - dt).total_seconds() / 60.0
        if mins < cooldown_minutes:
            return True
    return False


def _in_allowed_sessions(now: datetime, sessions: list[dict]) -> bool:
    if not sessions:
        return True
    current = now.strftime('%H:%M')
    for s in sessions:
        start = str(s.get('start', '')).strip()
        end = str(s.get('end', '')).strip()
        if start and end and start <= current < end:
            return True
    return False


def _held_minutes(open_position: dict | None, now: datetime | None = None) -> float:
    if not open_position:
        return 0.0
    dt = _parse_time(open_position.get('time', ''))
    if not dt:
        return 0.0
    ref = now or datetime.now()
    return (ref - dt).total_seconds() / 60.0


def _merge_config(config: dict | None = None) -> dict:
    default_config = {
        'buy': {
            'allowed_sessions': [{'start': '09:40', 'end': '10:40'}, {'start': '13:05', 'end': '14:08'}],
            'disable_new_buy_after': '14:08',
            'trend_rsi_min': 57,
            'trend_rsi_max': 76,
            'trend_volume_ratio': 0.98,
            'require_ma_uptrend': True,
            'min_ma5_rise_pct': 0.012,
            'min_ma10_rise_pct': 0.004,
            'max_rsi_for_entry': 69,
            'min_breakout_strength_pct': 0.20,
            'min_volume_ratio': 0.98,
            'max_pullback_pct': 0.35,
            'max_chase_above_ma5_pct': 0.28,
            'breakout_min_pct': 0.20,
            'pullback_min_pct': 0.03,
            'pullback_max_pct': 0.48,
            'kdj_trend_min': 45,
            'kdj_trend_max': 88,
            'allow_continuation_entry': True,
            'continuation_min_breakout_persistence_pct': 0.02,
            'continuation_min_rebound_strength_pct': 0.18,
            'continuation_max_ma5_gap_pct': 0.28,
            'continuation_min_volume_ratio': 1.00,
            'continuation_max_rsi': 67,
            'continuation_min_price_above_prev_high_pct': 0.0,
            'allow_reclaim_entry': True,
            'reclaim_min_rsi': 54,
            'reclaim_max_rsi': 66,
            'reclaim_min_volume_ratio': 1.01,
            'reclaim_min_pullback_pct': 0.10,
            'reclaim_max_pullback_pct': 0.38,
            'reclaim_min_rebound_strength_pct': 0.15,
            'reclaim_min_breakout_strength_pct': -0.10,
            'reclaim_min_breakout_persistence_pct': -0.40,
            'reclaim_min_ma5_gap_pct': -0.08,
            'reclaim_max_ma5_gap_pct': 0.10,
            'allow_late_strong_entry': True,
            'late_allowed_session': {'start': '14:08', 'end': '14:30'},
            'late_min_rsi': 64,
            'late_max_rsi': 82,
            'late_min_volume_ratio': 1.04,
            'late_min_breakout_strength_pct': 0.22,
            'late_min_breakout_persistence_pct': 0.05,
            'late_min_rebound_strength_pct': 0.35,
            'late_max_ma5_gap_pct': 0.28,
        },
        'sell': {
            'kdj_min': 999,
            'require_open_position': True,
            'require_below_ma5': True,
            'min_hold_minutes': 8,
            'ignore_kdj_sell_before_min_hold': True,
            'ignore_macd_sell_before_min_hold': True,
            'disable_macd_exit': True,
            'macd_sell_require_below_ma5': True,
            'macd_sell_profit_floor_pct': 9.99,
            'profit_protect_trigger_pct': 0.45,
            'profit_protect_ma5_buffer_pct': 0.0,
            'breakeven_trigger_pct': 0.35,
            'breakeven_buffer_pct': 0.03,
            'min_profit_for_ma5_exit_pct': 0.25,
            'use_ma_turn_exit': True,
            'ma_turn_profit_protect_pct': 0.05,
            'ma_turn_loss_cut_pct': -0.05,
            'ma10_turn_exit_on_loss': True,
            'loss_cut_soft_pct': 0.35,
            'force_flat_after': '14:47',
            'hard_flat_after': '14:54',
            'allow_overnight': False,
            'ma_turn_min_hold_minutes': 6,
            'take_profit_pct': 5.0,
            'stop_loss_pct': 0.65,
            'trailing_drawdown_pct': 0.9,
            'max_hold_minutes': 15,
            'stale_exit_minutes': 10,
            'stale_exit_max_profit_pct': 0.25,
            'stale_exit_profit_ceiling_pct': 0.05,
        },
        'stop_loss': 0.8,
        'take_profit': 1.4,
        'cooldown_minutes': 45,
        'max_new_buys_per_cycle': 4,
        'atr': {
            'period': 14,
            'stop_loss_multiplier': 1.5,
            'take_profit_multiplier': 2.6,
            'min_stop_loss_pct': 0.55,
            'max_stop_loss_pct': 0.95,
            'enable_trailing_take_profit': True,
            'trailing_buffer_multiplier': 0.8,
        }
    }
    cfg = {**default_config, **(config or {})}
    cfg['buy'] = {**default_config['buy'], **((config or {}).get('buy', {}))}
    cfg['sell'] = {**default_config['sell'], **((config or {}).get('sell', {}))}
    cfg['atr'] = {**default_config['atr'], **((config or {}).get('atr', {}))}
    return cfg


def detect_buy_signal(code: str, name: str, indicators: dict, config: dict | None = None, fast_mode: bool = False, now: datetime | None = None) -> dict | None:
    if indicators is None:
        return None
    cfg = _merge_config(config)
    now = now or datetime.now()
    current_hm = now.strftime('%H:%M')

    macd_dif = float(indicators.get('macd_dif', 0) or 0)
    macd_dea = float(indicators.get('macd_dea', 0) or 0)
    prev_macd_dif = float(indicators.get('prev_macd_dif', 0) or 0)
    rsi = float(indicators.get('rsi', 50) or 50)
    close = float(indicators.get('close', 0) or 0)
    ma5 = float(indicators.get('ma5', 0) or 0)
    ma10 = float(indicators.get('ma10', 0) or 0)
    atr = float(indicators.get('atr', 0) or 0)
    volume_ratio = float(indicators.get('volume_ratio', indicators.get('vma5', 1)) or 1)
    prev_ma5 = float(indicators.get('prev_ma5', 0) or 0)
    prev_ma10 = float(indicators.get('prev_ma10', 0) or 0)
    ma5_rise_pct = ((ma5 - prev_ma5) / prev_ma5 * 100) if prev_ma5 > 0 else 0
    ma10_rise_pct = ((ma10 - prev_ma10) / prev_ma10 * 100) if prev_ma10 > 0 else 0
    trend_ok = bool(indicators.get('trend_ok', False))
    re_stabilize = bool(indicators.get('re_stabilize', False))
    breakout_strength_pct = float(indicators.get('breakout_strength_pct', 0) or 0)
    pullback_pct = float(indicators.get('pullback_pct', 0) or 0)
    ma5_gap_pct = float(indicators.get('ma5_gap_pct', 0) or 0)
    rebound_strength_pct = float(indicators.get('rebound_strength_pct', 0) or 0)
    breakout_persistence_pct = float(indicators.get('breakout_persistence_pct', 0) or 0)
    price_above_prev_high_pct = float(indicators.get('price_above_prev_high_pct', 0) or 0)

    ma_uptrend_ok = (ma5 > prev_ma5 > 0) and (ma10 >= prev_ma10 > 0) if cfg['buy'].get('require_ma_uptrend', True) else True
    session_ok = _in_allowed_sessions(now, cfg['buy'].get('allowed_sessions', []))
    buy_time_ok = current_hm < str(cfg['buy'].get('disable_new_buy_after', '14:08'))
    rsi_cap = min(float(cfg['buy'].get('trend_rsi_max', 76)), float(cfg['buy'].get('max_rsi_for_entry', 69)))
    trend_filter_ok = all([
        trend_ok,
        ma_uptrend_ok,
        session_ok,
        buy_time_ok,
        cfg['buy'].get('trend_rsi_min', 57) <= rsi <= rsi_cap,
        volume_ratio >= max(float(cfg['buy'].get('trend_volume_ratio', 0.98)), float(cfg['buy'].get('min_volume_ratio', 0.98))),
        macd_dif >= macd_dea,
        macd_dif >= prev_macd_dif,
        close >= ma10,
        ma5_rise_pct >= float(cfg['buy'].get('min_ma5_rise_pct', 0.012)),
        ma10_rise_pct >= float(cfg['buy'].get('min_ma10_rise_pct', 0.004)),
    ])

    pullback_entry_ok = all([
        trend_filter_ok,
        re_stabilize,
        -0.08 <= ma5_gap_pct <= float(cfg['buy'].get('max_chase_above_ma5_pct', 0.28)),
        float(cfg['buy'].get('pullback_min_pct', 0.03)) <= pullback_pct <= min(float(cfg['buy'].get('pullback_max_pct', 0.48)), float(cfg['buy'].get('max_pullback_pct', 0.35))),
        breakout_strength_pct >= max(float(cfg['buy'].get('breakout_min_pct', 0.20)), float(cfg['buy'].get('min_breakout_strength_pct', 0.20))),
    ])

    continuation_entry_ok = all([
        trend_filter_ok,
        re_stabilize,
        bool(cfg['buy'].get('allow_continuation_entry', True)),
        rsi <= float(cfg['buy'].get('continuation_max_rsi', 67)),
        breakout_strength_pct >= max(float(cfg['buy'].get('breakout_min_pct', 0.20)), float(cfg['buy'].get('min_breakout_strength_pct', 0.20))),
        breakout_persistence_pct >= float(cfg['buy'].get('continuation_min_breakout_persistence_pct', 0.02)),
        rebound_strength_pct >= float(cfg['buy'].get('continuation_min_rebound_strength_pct', 0.18)),
        -0.05 <= ma5_gap_pct <= float(cfg['buy'].get('continuation_max_ma5_gap_pct', 0.28)),
        volume_ratio >= float(cfg['buy'].get('continuation_min_volume_ratio', 1.00)),
        close >= ma5,
        price_above_prev_high_pct >= float(cfg['buy'].get('continuation_min_price_above_prev_high_pct', 0.0)),
        pullback_pct <= 0.22,
    ])

    reclaim_entry_ok = all([
        trend_ok,
        bool(cfg['buy'].get('allow_reclaim_entry', True)),
        session_ok,
        buy_time_ok,
        re_stabilize,
        ma_uptrend_ok,
        float(cfg['buy'].get('reclaim_min_rsi', 54)) <= rsi <= float(cfg['buy'].get('reclaim_max_rsi', 66)),
        volume_ratio >= float(cfg['buy'].get('reclaim_min_volume_ratio', 1.01)),
        float(cfg['buy'].get('reclaim_min_pullback_pct', 0.10)) <= pullback_pct <= float(cfg['buy'].get('reclaim_max_pullback_pct', 0.38)),
        float(cfg['buy'].get('reclaim_min_breakout_strength_pct', -0.10)) <= breakout_strength_pct <= float(cfg['buy'].get('min_breakout_strength_pct', 0.20)),
        breakout_persistence_pct >= float(cfg['buy'].get('reclaim_min_breakout_persistence_pct', -0.40)),
        rebound_strength_pct >= float(cfg['buy'].get('reclaim_min_rebound_strength_pct', 0.15)),
        float(cfg['buy'].get('reclaim_min_ma5_gap_pct', -0.08)) <= ma5_gap_pct <= float(cfg['buy'].get('reclaim_max_ma5_gap_pct', 0.10)),
        close >= ma5,
    ])

    late_session = cfg['buy'].get('late_allowed_session', {'start': '14:08', 'end': '14:30'})
    late_session_ok = _in_allowed_sessions(now, [late_session])
    late_strong_entry_ok = all([
        trend_ok,
        bool(cfg['buy'].get('allow_late_strong_entry', True)),
        late_session_ok,
        re_stabilize,
        ma_uptrend_ok,
        float(cfg['buy'].get('late_min_rsi', 64)) <= rsi <= float(cfg['buy'].get('late_max_rsi', 82)),
        volume_ratio >= float(cfg['buy'].get('late_min_volume_ratio', 1.04)),
        breakout_strength_pct >= float(cfg['buy'].get('late_min_breakout_strength_pct', 0.22)),
        breakout_persistence_pct >= float(cfg['buy'].get('late_min_breakout_persistence_pct', 0.05)),
        rebound_strength_pct >= float(cfg['buy'].get('late_min_rebound_strength_pct', 0.35)),
        0.0 <= ma5_gap_pct <= float(cfg['buy'].get('late_max_ma5_gap_pct', 0.28)),
        close >= ma5 >= ma10,
    ])

    if not (pullback_entry_ok or continuation_entry_ok or reclaim_entry_ok or late_strong_entry_ok):
        return None

    if pullback_entry_ok:
        entry_style = 'pullback'
        reason = f"突破后首次回踩 + RSI({rsi:.1f}) + 量比({volume_ratio:.2f}x) + 回踩({pullback_pct:.2f}%) + 贴近MA5({ma5_gap_pct:.2f}%)"
    elif continuation_entry_ok:
        entry_style = 'continuation'
        reason = f"强势延续 + RSI({rsi:.1f}) + 量比({volume_ratio:.2f}x) + 突破保持({breakout_persistence_pct:.2f}%) + 反弹({rebound_strength_pct:.2f}%)"
    elif reclaim_entry_ok:
        entry_style = 'reclaim'
        reason = f"MA5 回收再走强 + RSI({rsi:.1f}) + 量比({volume_ratio:.2f}x) + 回踩({pullback_pct:.2f}%) + 反弹({rebound_strength_pct:.2f}%)"
    else:
        entry_style = 'late_strong'
        reason = f"尾盘强突破 + RSI({rsi:.1f}) + 量比({volume_ratio:.2f}x) + 突破保持({breakout_persistence_pct:.2f}%) + 反弹({rebound_strength_pct:.2f}%)"

    return {
        'type': 'BUY', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'reason': reason,
        'indicators': {
            'macd_dif': macd_dif, 'macd_dea': macd_dea, 'rsi': rsi, 'volume_ratio': volume_ratio, 'ma5': ma5, 'ma10': ma10,
            'prev_ma5': prev_ma5, 'prev_ma10': prev_ma10, 'ma5_rise_pct': ma5_rise_pct, 'ma10_rise_pct': ma10_rise_pct,
            'atr': atr, 'pullback_pct': pullback_pct, 'ma5_gap_pct': ma5_gap_pct, 'breakout_strength_pct': breakout_strength_pct,
            'rebound_strength_pct': rebound_strength_pct, 'breakout_persistence_pct': breakout_persistence_pct,
            'price_above_prev_high_pct': price_above_prev_high_pct, 'entry_style': entry_style,
        },
        'confidence': 'HIGH', 'status': 'OPEN', 'fast_mode': fast_mode
    }


def detect_sell_signal(code: str, name: str, indicators: dict, open_position: dict | None, config: dict | None = None, now: datetime | None = None) -> dict | None:
    if indicators is None or not open_position:
        return None
    cfg = _merge_config(config)
    now = now or datetime.now()

    close = float(indicators.get('close', 0) or 0)
    buy_price = float(open_position.get('price', 0) or 0)
    if buy_price <= 0 or close <= 0:
        return None

    profit_pct_now = ((close - buy_price) / buy_price) * 100
    held_minutes = _held_minutes(open_position, now=now)
    buy_dt = _parse_time(open_position.get('time', ''))

    sell_cfg = cfg.get('sell', {})
    allow_overnight = bool(sell_cfg.get('allow_overnight', False))
    take_profit_pct = float(sell_cfg.get('take_profit_pct', 5.0) or 5.0)
    stop_loss_pct = float(sell_cfg.get('stop_loss_pct', 0.65) or 0.65)
    trailing_drawdown_pct = float(sell_cfg.get('trailing_drawdown_pct', 0.9) or 0.9)
    max_hold_minutes = float(sell_cfg.get('max_hold_minutes', 15) or 15)
    stale_exit_minutes = float(sell_cfg.get('stale_exit_minutes', 10) or 10)
    stale_exit_max_profit_pct = float(sell_cfg.get('stale_exit_max_profit_pct', 0.25) or 0.25)
    stale_exit_profit_ceiling_pct = float(sell_cfg.get('stale_exit_profit_ceiling_pct', 0.05) or 0.05)

    recorded_max_profit = float(open_position.get('max_profit_pct', 0) or 0)
    max_profit_pct = max(recorded_max_profit, profit_pct_now)
    if max_profit_pct != recorded_max_profit:
        open_position['max_profit_pct'] = round(max_profit_pct, 4)

    if buy_dt and not allow_overnight and buy_dt.date() != now.date():
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': '跨日补救强制平仓',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    if profit_pct_now >= take_profit_pct:
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': f'固定止盈触发 ({profit_pct_now:.2f}% >= {take_profit_pct:.2f}%)',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    if profit_pct_now <= -abs(stop_loss_pct):
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': f'固定止损触发 ({profit_pct_now:.2f}% <= -{abs(stop_loss_pct):.2f}%)',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    if held_minutes >= stale_exit_minutes and max_profit_pct <= stale_exit_max_profit_pct and profit_pct_now <= stale_exit_profit_ceiling_pct:
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': f'弱势超时离场 ({held_minutes:.1f} 分钟, 最高浮盈 {max_profit_pct:.2f}%, 当前 {profit_pct_now:.2f}%)',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    if max_profit_pct > 0 and (max_profit_pct - profit_pct_now) >= trailing_drawdown_pct:
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': f'盈利回撤止盈/止损触发 (最高浮盈 {max_profit_pct:.2f}% -> 当前 {profit_pct_now:.2f}%，回撤 {(max_profit_pct - profit_pct_now):.2f}% >= {trailing_drawdown_pct:.2f}%)',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    if held_minutes >= max_hold_minutes:
        return {
            'type': 'SELL', 'code': code, 'name': name, 'price': close, 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'reason': f'超时强制平仓 ({held_minutes:.1f} 分钟 >= {max_hold_minutes:.1f} 分钟)',
            'indicators': {'close': close, 'buy_price': buy_price, 'profit_pct': profit_pct_now, 'held_minutes': held_minutes, 'max_profit_pct': max_profit_pct},
            'confidence': 'HIGH', 'status': 'CLOSE'
        }

    return None


def generate_signals(code: str, name: str, indicators: dict, config: dict = None, fast_mode: bool = False) -> List[dict]:
    signals = []
    if indicators is None:
        return signals

    cfg = _merge_config(config)
    trades = load_trades()
    cooldown_minutes = int(cfg.get('cooldown_minutes', 45) or 0)
    open_position = find_open_position(code, trades)
    if open_position:
        buy_price = float(open_position.get('price', 0) or 0)
        close = float(indicators.get('close', 0) or 0)
        if buy_price > 0 and close > 0:
            cur_profit_pct = ((close - buy_price) / buy_price) * 100
            prev_max_profit_pct = float(open_position.get('max_profit_pct', 0) or 0)
            if cur_profit_pct > prev_max_profit_pct:
                open_position['max_profit_pct'] = round(cur_profit_pct, 4)
                save_trades(trades)

    buy_signal = detect_buy_signal(code, name, indicators, cfg, fast_mode=fast_mode)
    if buy_signal and (not open_position) and (not _recent_same_signal(code, 'BUY', cooldown_minutes, trades)):
        signals.append(buy_signal)

    if cfg['sell'].get('require_open_position', True) and not open_position:
        return signals
    if _recent_same_signal(code, 'SELL', cooldown_minutes, trades):
        return signals

    sell_signal = detect_sell_signal(code, name, indicators, open_position, cfg)
    if sell_signal:
        signals.append(sell_signal)
    return signals



def sync_signal_states(signal: dict, linked_buy: dict | None = None):
    if not os.path.exists(SIGNALS_FILE):
        return
    try:
        with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
            signals = json.load(f)
        changed = False
        if signal.get('type') == 'SELL' and linked_buy:
            buy_code = linked_buy.get('code')
            buy_time = linked_buy.get('time')
            for item in signals:
                if item.get('type') == 'BUY' and item.get('status') == 'OPEN' and item.get('code') == buy_code and item.get('time') == buy_time:
                    item['status'] = 'CLOSED'
                    item['sell_time'] = signal.get('time')
                    item['sell_price'] = signal.get('price')
                    item['sell_reason'] = signal.get('reason')
                    changed = True
            exists = any(
                item.get('type') == 'SELL' and item.get('code') == signal.get('code') and item.get('time') == signal.get('time') and item.get('reason') == signal.get('reason')
                for item in signals
            )
            if not exists:
                signals.append(signal)
                changed = True
        elif signal.get('type') == 'BUY':
            exists = any(
                item.get('type') == 'BUY' and item.get('code') == signal.get('code') and item.get('time') == signal.get('time') and item.get('reason') == signal.get('reason')
                for item in signals
            )
            if not exists:
                signals.append(signal)
                changed = True
        if changed:
            signals = signals[-400:]
            with open(SIGNALS_FILE, 'w', encoding='utf-8') as f:
                json.dump(signals, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def rank_new_buy_signals(signals: list, config: dict | None = None) -> list:
    if not signals:
        return []
    cfg = _merge_config(config)
    max_new_buys = int(cfg.get('max_new_buys_per_cycle', 4) or 4)

    buys = [s for s in signals if s.get('type') == 'BUY']
    others = [s for s in signals if s.get('type') != 'BUY']
    if not buys:
        return signals

    def score(sig: dict):
        ind = sig.get('indicators', {}) or {}
        style = str(ind.get('entry_style', '') or '')
        style_bonus = {
            'pullback': 0.30,
            'reclaim': 0.18,
            'continuation': 0.10,
            'late_strong': 0.12,
        }.get(style, 0.0)
        return (
            style_bonus,
            float(ind.get('breakout_strength_pct', 0) or 0),
            float(ind.get('rebound_strength_pct', 0) or 0),
            float(ind.get('volume_ratio', 0) or 0),
            -abs(float(ind.get('pullback_pct', 0) or 0) - 0.14),
            -abs(float(ind.get('ma5_gap_pct', 0) or 0)),
            -abs(float(ind.get('rsi', 0) or 0) - 62),
        )

    buys = sorted(buys, key=score, reverse=True)[:max_new_buys]
    return buys + others


def process_signal(signal: dict) -> dict:
    trades = load_trades()
    result = {'signal': signal, 'trade_record': None, 'profit': None}
    if signal['type'] == 'BUY':
        result['trade_record'] = {'id': f"{signal['code']}_{len(trades)}_{datetime.now().strftime('%Y%m%d%H%M%S')}", 'code': signal['code'], 'name': signal['name'], 'type': 'BUY', 'price': signal['price'], 'time': signal['time'], 'status': 'OPEN', 'reason': signal['reason'], 'max_profit_pct': 0.0}
        trades.append(result['trade_record'])
        sync_signal_states(signal)
    elif signal['type'] == 'SELL':
        open_position = find_open_position(signal['code'], trades)
        if open_position:
            profit_info = calculate_profit(open_position['price'], signal['price'])
            for trade in trades:
                if trade['id'] == open_position['id']:
                    trade['status'] = 'CLOSED'
                    trade['sell_price'] = signal['price']
                    trade['sell_time'] = signal['time']
                    trade['profit'] = profit_info['profit']
                    trade['profit_pct'] = profit_info['profit_pct']
            sell_record = {'id': f"{signal['code']}_SELL_{datetime.now().strftime('%Y%m%d%H%M%S')}", 'code': signal['code'], 'name': signal['name'], 'type': 'SELL', 'price': signal['price'], 'time': signal['time'], 'status': 'CLOSED', 'reason': signal['reason'], 'linked_buy_id': open_position['id'], 'buy_price': open_position['price'], 'buy_time': open_position['time'], 'profit': profit_info['profit'], 'profit_pct': profit_info['profit_pct']}
            trades.append(sell_record)
            result['trade_record'] = sell_record
            result['profit'] = profit_info
            sync_signal_states(signal, linked_buy=open_position)
    save_trades(trades)
    return result


def get_trade_history(limit: int = 20) -> list:
    trades = load_trades()
    closed_trades = [t for t in trades if t.get('status') == 'CLOSED' and t['type'] == 'SELL']
    closed_trades.sort(key=lambda x: x['time'], reverse=True)
    return closed_trades[:limit]


def format_trade(trade: dict) -> str:
    profit_emoji = '+' if trade['profit_pct'] > 0 else '-' if trade['profit_pct'] < 0 else '='
    return f"""
{profit_emoji} {trade['code']} ({trade['name']})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
买入：{trade.get('buy_time', '')[5:16]} @ ¥{trade.get('buy_price', 0):.3f}
卖出：{trade.get('time', '')[5:16]} @ ¥{trade.get('price', 0):.3f}
盈亏：{trade.get('profit_pct', 0):+6.2f}% (¥{trade.get('profit', 0):+6.4f})
原因：{trade.get('reason', '')}
""".strip()


def format_signal(signal: dict) -> str:
    emoji = 'BUY' if signal['type'] == 'BUY' else 'SELL'
    confidence = signal.get('confidence', 'MEDIUM')
    fast_tag = ' ⚡' if signal.get('fast_mode') else ''
    return f"""
{emoji} {signal['type']}{fast_tag} - {signal['code']} ({signal['name']})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
时间：{signal['time'][11:19]}
价格：¥{signal['price']:.3f}
置信度：{confidence}
原因：{signal['reason']}
""".strip()


if __name__ == '__main__':
    print('Signal engine OK')
