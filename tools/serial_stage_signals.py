#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串行换仓阶段买点原型：不替换原主策略，只作为并行研究信号模块。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


SERIAL_STAGE_SPECS = [
    {
        'name': 'S1_1130_repair',
        'start_hm': '11:30', 'end_hm': '11:30', 'hold_minutes': 30,
        'min_rsi': 35, 'max_rsi': 56,
        'min_vr': 0.2, 'max_vr': 0.35,
        'min_reb': 0.0, 'max_reb': 0.6,
        'min_pb': 0.15, 'max_pb': 1.4,
        'min_gap': -0.2, 'max_gap': 0.15,
        'min_band_pos': 0.1, 'max_band_pos': 0.5,
        'min_bos': -0.2, 'max_bos': 0.05,
        'min_bop': -1.6, 'max_bop': -0.2,
        'require_re_stabilize': True,
        'require_trend_true': False,
        'require_trend_false': False,
        'score_cols': ['pullback_pct', 'rebound_strength_pct', 'volume_ratio'],
    },
    {
        'name': 'S1_1130_trend',
        'start_hm': '11:30', 'end_hm': '11:30', 'hold_minutes': 30,
        'min_rsi': 55, 'max_rsi': 100,
        'min_vr': 0.2, 'max_vr': 1.6,
        'min_reb': 0.0, 'max_reb': 1.5,
        'min_pb': 0.0, 'max_pb': 0.8,
        'min_gap': -0.2, 'max_gap': 0.4,
        'min_band_pos': 0.45, 'max_band_pos': 0.9,
        'min_bos': -0.2, 'max_bos': 0.2,
        'min_bop': -0.8, 'max_bop': 0.1,
        'require_re_stabilize': True,
        'require_trend_true': False,
        'require_trend_false': False,
        'score_cols': ['rebound_strength_pct', 'ma5_gap_pct', 'volume_ratio'],
    },
    {
        'name': 'S2_1300_reversal',
        'start_hm': '13:00', 'end_hm': '13:15', 'hold_minutes': 30,
        'min_rsi': 38, 'max_rsi': 58,
        'min_vr': 1.15, 'max_vr': 1.4,
        'min_reb': 0.15, 'max_reb': 1.5,
        'min_pb': 0.6, 'max_pb': 2.0,
        'min_gap': 0.0, 'max_gap': 0.4,
        'min_band_pos': 0.12, 'max_band_pos': 0.45,
        'min_bos': -1.2, 'max_bos': 0.1,
        'min_bop': -3.0, 'max_bop': -0.5,
        'require_re_stabilize': True,
        'require_trend_true': False,
        'require_trend_false': True,
        'score_cols': ['pullback_pct', 'rebound_strength_pct', 'volume_ratio'],
    },
    {
        'name': 'S3_1410_tail',
        'start_hm': '14:00', 'end_hm': '14:15', 'hold_minutes': 30,
        'min_rsi': 50, 'max_rsi': 100,
        'min_vr': 0.9, 'max_vr': 1.35,
        'min_reb': 0.0, 'max_reb': 1.5,
        'min_pb': 0.0, 'max_pb': 0.8,
        'min_gap': -0.1, 'max_gap': 0.3,
        'min_band_pos': 0.45, 'max_band_pos': 1.1,
        'min_bos': -0.1, 'max_bos': 0.2,
        'min_bop': -0.8, 'max_bop': 0.0,
        'require_re_stabilize': False,
        'require_trend_true': False,
        'require_trend_false': False,
        'score_cols': ['rebound_strength_pct', 'volume_ratio', 'ma5_gap_pct'],
    },
]


def _passes_stage(indicators: dict, spec: dict, now: datetime) -> bool:
    hm = now.strftime('%H:%M')
    rsi = float(indicators.get('rsi', 0) or 0)
    vr = float(indicators.get('volume_ratio', 0) or 0)
    pb = float(indicators.get('pullback_pct', 0) or 0)
    gap = float(indicators.get('ma5_gap_pct', 0) or 0)
    bos = float(indicators.get('breakout_strength_pct', 0) or 0)
    bop = float(indicators.get('breakout_persistence_pct', 0) or 0)
    reb = float(indicators.get('rebound_strength_pct', 0) or 0)
    trend_ok = bool(indicators.get('trend_ok', False))
    re_stabilize = bool(indicators.get('re_stabilize', False))
    band_pos = float(indicators.get('band_pos', 0.5) or 0.5)

    return (
        spec['start_hm'] <= hm <= spec['end_hm']
        and spec['min_rsi'] <= rsi <= spec['max_rsi']
        and spec['min_vr'] <= vr <= spec['max_vr']
        and spec['min_reb'] <= reb <= spec['max_reb']
        and spec['min_pb'] <= pb <= spec['max_pb']
        and spec['min_gap'] <= gap <= spec['max_gap']
        and spec['min_band_pos'] <= band_pos <= spec['max_band_pos']
        and spec['min_bos'] <= bos <= spec['max_bos']
        and spec['min_bop'] <= bop <= spec['max_bop']
        and (not spec['require_re_stabilize'] or re_stabilize)
        and (not spec['require_trend_true'] or trend_ok)
        and (not spec['require_trend_false'] or (not trend_ok))
    )


def _stage_score(indicators: dict, spec: dict) -> float:
    total = 0.0
    for c in spec['score_cols']:
        v = float(indicators.get(c, 0) or 0)
        total += v * 100.0 if abs(v) < 5 else v
    return round(total, 4)


def detect_serial_stage_buy_signal(code: str, name: str, indicators: dict, now: Optional[datetime] = None, open_position: Optional[dict] = None) -> dict | None:
    now = now or datetime.now()
    if open_position:
        return None

    matched = []
    for spec in SERIAL_STAGE_SPECS:
        if _passes_stage(indicators, spec, now):
            matched.append((spec, _stage_score(indicators, spec)))
    if not matched:
        return None
    matched.sort(key=lambda x: x[1], reverse=True)
    spec, score = matched[0]
    price = float(indicators.get('close', 0) or 0)
    if price <= 0:
        return None
    exit_time = now + timedelta(minutes=int(spec['hold_minutes']))
    return {
        'type': 'BUY',
        'code': str(code),
        'name': str(name),
        'price': round(price, 4),
        'time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'reason': f"{spec['name']}:score={score:.2f} rsi={float(indicators.get('rsi',0) or 0):.1f} vr={float(indicators.get('volume_ratio',0) or 0):.2f} pb={float(indicators.get('pullback_pct',0) or 0):.3f} reb={float(indicators.get('rebound_strength_pct',0) or 0):.3f} gap={float(indicators.get('ma5_gap_pct',0) or 0):.3f}",
        'strategy_family': 'serial_stage_rotation',
        'stage_name': spec['name'],
        'planned_hold_minutes': int(spec['hold_minutes']),
        'planned_exit_time': exit_time.strftime('%Y-%m-%d %H:%M:%S'),
        'score': score,
        'indicators': {
            'rsi': float(indicators.get('rsi', 0) or 0),
            'volume_ratio': float(indicators.get('volume_ratio', 0) or 0),
            'pullback_pct': float(indicators.get('pullback_pct', 0) or 0),
            'ma5_gap_pct': float(indicators.get('ma5_gap_pct', 0) or 0),
            'breakout_strength_pct': float(indicators.get('breakout_strength_pct', 0) or 0),
            'breakout_persistence_pct': float(indicators.get('breakout_persistence_pct', 0) or 0),
            'rebound_strength_pct': float(indicators.get('rebound_strength_pct', 0) or 0),
            'trend_ok': bool(indicators.get('trend_ok', False)),
            're_stabilize': bool(indicators.get('re_stabilize', False)),
            'band_pos': float(indicators.get('band_pos', 0.5) or 0.5),
        },
    }
