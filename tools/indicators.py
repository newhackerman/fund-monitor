#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术指标计算模块（兼容版）"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import talib as _talib  # type: ignore
except Exception:
    _talib = None


class _TalibFallback:
    @staticmethod
    def _s(values) -> pd.Series:
        return pd.Series(values, dtype='float64')

    @staticmethod
    def SMA(values, timeperiod: int = 5):
        s = _TalibFallback._s(values)
        n = int(timeperiod)
        return s.rolling(n, min_periods=n).mean().to_numpy()

    @staticmethod
    def _EMA(values, period: int):
        s = _TalibFallback._s(values)
        n = int(period)
        return s.ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()

    @staticmethod
    def MACD(values, fastperiod: int = 12, slowperiod: int = 26, signalperiod: int = 9):
        fast = _TalibFallback._EMA(values, fastperiod)
        slow = _TalibFallback._EMA(values, slowperiod)
        dif = fast - slow
        dea = pd.Series(dif, dtype='float64').ewm(span=int(signalperiod), adjust=False, min_periods=int(signalperiod)).mean().to_numpy()
        hist = dif - dea
        return dif, dea, hist

    @staticmethod
    def RSI(values, timeperiod: int = 14):
        s = _TalibFallback._s(values)
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        n = int(timeperiod)
        alpha = 1.0 / float(n)
        avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=n).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=n).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0).to_numpy()

    @staticmethod
    def BBANDS(values, timeperiod: int = 20, nbdevup: float = 2, nbdevdn: float = 2, matype: int = 0):
        s = _TalibFallback._s(values)
        n = int(timeperiod)
        mid = s.rolling(n, min_periods=n).mean()
        std = s.rolling(n, min_periods=n).std(ddof=0)
        upper = mid + std * float(nbdevup)
        lower = mid - std * float(nbdevdn)
        return upper.to_numpy(), mid.to_numpy(), lower.to_numpy()

    @staticmethod
    def ATR(high, low, close, timeperiod: int = 14):
        h = _TalibFallback._s(high)
        l = _TalibFallback._s(low)
        c = _TalibFallback._s(close)
        prev_close = c.shift(1)
        tr = pd.concat([(h - l).abs(), (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
        n = int(timeperiod)
        atr = tr.ewm(alpha=1.0 / float(n), adjust=False, min_periods=n).mean()
        return atr.fillna(0.0).to_numpy()


if _talib is None:
    talib = _TalibFallback()
else:
    talib = _talib


def validate_dataframe(df: pd.DataFrame) -> bool:
    if df is None or len(df) == 0:
        return False
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            logger.error(f'缺少必要列：{col}')
            return False
    if (df['close'] <= 0).any():
        logger.error('收盘价包含非正值')
        return False
    if (df['high'] < df['low']).any():
        logger.error('最高价小于最低价')
        return False
    return True


def calculate_indicators(df: pd.DataFrame, config: dict | None = None, fast_mode: bool = False) -> pd.DataFrame | None:
    if not validate_dataframe(df):
        return None
    try:
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna()
        min_required = 15 if not fast_mode else 30
        if len(df) < min_required:
            logger.error(f'数据量不足 ({len(df)}条)，需要至少 {min_required} 条')
            return None
        atr_cfg = config.get('atr', {'period': 14}) if config else {'period': 14}
        atr_period = atr_cfg.get('period', 14)
        macd_cfg = config.get('macd', {'fast': 12, 'slow': 26, 'signal': 9}) if config else {}
        rsi_cfg = config.get('rsi', {'period': 14}) if config else {}
        boll_cfg = config.get('bollinger', {'period': 20, 'std': 2}) if config else {}
        df['MACD_DIF'], df['MACD_DEA'], df['MACD_HIST'] = talib.MACD(df['close'].values, fastperiod=macd_cfg.get('fast', 12), slowperiod=macd_cfg.get('slow', 26), signalperiod=macd_cfg.get('signal', 9))
        df['RSI'] = talib.RSI(df['close'].values, timeperiod=rsi_cfg.get('period', 14))
        df['BOLL_UPPER'], df['BOLL_MIDDLE'], df['BOLL_LOWER'] = talib.BBANDS(df['close'].values, timeperiod=boll_cfg.get('period', 20), nbdevup=boll_cfg.get('std', 2), nbdevdn=boll_cfg.get('std', 2), matype=0)
        df['MA5'] = talib.SMA(df['close'].values, timeperiod=5)
        df['MA10'] = talib.SMA(df['close'].values, timeperiod=10)
        df['MA20'] = talib.SMA(df['close'].values, timeperiod=20)
        df['VMA5'] = talib.SMA(df['volume'].values, timeperiod=5)
        df['ATR'] = talib.ATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=atr_period)
        df = df.ffill().fillna(0)
        return df
    except Exception as e:
        logger.error(f'计算指标失败：{e}', exc_info=True)
        return None


def get_latest_indicators(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 2:
        return None
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        def safe_float(val, default=0.0):
            try:
                return float(val) if pd.notna(val) else float(default)
            except Exception:
                return float(default)
        return {
            'macd_dif': safe_float(last.get('MACD_DIF'), 0), 'macd_dea': safe_float(last.get('MACD_DEA'), 0), 'macd_hist': safe_float(last.get('MACD_HIST'), 0),
            'rsi': safe_float(last.get('RSI'), 50), 'close': safe_float(last.get('close'), 0), 'volume': safe_float(last.get('volume'), 0),
            'vma5': safe_float(last.get('VMA5'), 1), 'ma5': safe_float(last.get('MA5'), 0), 'ma10': safe_float(last.get('MA10'), 0), 'ma20': safe_float(last.get('MA20'), 0), 'atr': safe_float(last.get('ATR'), 0),
            'prev_ma5': safe_float(prev.get('MA5'), 0), 'prev_ma10': safe_float(prev.get('MA10'), 0), 'prev_ma20': safe_float(prev.get('MA20'), 0),
            'prev_macd_dif': safe_float(prev.get('MACD_DIF'), 0), 'prev_macd_dea': safe_float(prev.get('MACD_DEA'), 0),
        }
    except Exception as e:
        logger.error(f'获取最新指标失败：{e}')
        return None


def _slope_pct(series: pd.Series, window: int = 5) -> float:
    s = pd.to_numeric(series.tail(window), errors='coerce').dropna()
    if len(s) < 3:
        return 0.0
    y = s.to_numpy(dtype='float64')
    x = np.arange(len(y), dtype='float64')
    slope = np.polyfit(x, y, 1)[0]
    base = float(np.mean(y[:-1])) if len(y) > 1 else float(y[-1])
    if abs(base) < 1e-12:
        return 0.0
    return float(slope / base * 100)


def extract_signal_context(df: pd.DataFrame, lookback: int = 25) -> dict | None:
    if df is None or len(df) < max(lookback, 25):
        return None
    try:
        tail = df.tail(lookback).reset_index(drop=True)
        last = tail.iloc[-1]
        prev = tail.iloc[-2]
        recent = tail.iloc[-15:]
        prev_block = tail.iloc[-25:-5] if len(tail) >= 25 else tail.iloc[:-5]
        close = float(last['close'])
        prev_close = float(prev['close'])
        ma5 = float(last['MA5']) if pd.notna(last['MA5']) else 0.0
        ma10 = float(last['MA10']) if pd.notna(last['MA10']) else 0.0
        ma20 = float(last['MA20']) if pd.notna(last['MA20']) else 0.0
        volume = float(last['volume']) if pd.notna(last['volume']) else 0.0
        prev_volume = float(prev['volume']) if pd.notna(prev['volume']) else 0.0
        vma5 = float(last['VMA5']) if pd.notna(last['VMA5']) else 1.0
        ctx = get_latest_indicators(df) or {}

        recent_high = float(recent['high'].max()) if len(recent) else float(last['high'])
        recent_low = float(recent['low'].min()) if len(recent) else float(last['low'])
        prev_high = float(prev_block['high'].max()) if len(prev_block) else recent_high
        breakout_strength_pct = ((recent_high - prev_high) / prev_high * 100) if prev_high > 0 else 0.0
        pullback_pct = ((recent_high - close) / recent_high * 100) if recent_high > 0 else 0.0
        ma5_gap_pct = ((close - ma5) / ma5 * 100) if ma5 > 0 else 0.0
        volume_ratio = (volume / vma5) if vma5 > 0 else 1.0
        trend_ok = close >= ma20 and ma5 >= ma10 >= ma20 if ma20 > 0 else False

        ma5_slope_pct = _slope_pct(tail['MA5'], window=5)
        ma10_slope_pct = _slope_pct(tail['MA10'], window=7)
        price_above_prev_high_pct = ((close - prev_high) / prev_high * 100) if prev_high > 0 else 0.0

        pullback_zone = recent.tail(5) if len(recent) >= 5 else recent
        pullback_low = float(pullback_zone['low'].min()) if len(pullback_zone) else recent_low
        rebound_strength_pct = ((close - pullback_low) / pullback_low * 100) if pullback_low > 0 else 0.0

        volume_accel_ratio = (volume / prev_volume) if prev_volume > 0 else 1.0
        close_diff = recent['close'].diff().fillna(0)
        recent_up_bars = int((close_diff > 0).sum())
        recent_green_ratio = (recent_up_bars / max(len(recent) - 1, 1)) if len(recent) > 1 else 0.0

        breakout_zone = recent.tail(3) if len(recent) >= 3 else recent
        breakout_persistence_pct = ((float(breakout_zone['close'].min()) - prev_high) / prev_high * 100) if len(breakout_zone) and prev_high > 0 else 0.0

        # 放宽 re_stabilize：更贴近研究数据集口径，强调“回落后止跌回稳/反弹恢复”
        macd_soft_ok = float(last['MACD_DIF']) >= float(prev['MACD_DIF'])
        price_recover_ok = close >= prev_close or rebound_strength_pct >= 0.15
        re_stabilize = bool(price_recover_ok and (macd_soft_ok or ma5_gap_pct >= 0))

        ctx.update({
            'recent_high': recent_high,
            'prev_block_high': prev_high,
            'breakout_happened': recent_high >= prev_high * 1.002 if prev_high > 0 else False,
            'breakout_strength_pct': breakout_strength_pct,
            'pullback_pct': pullback_pct,
            'ma5_gap_pct': ma5_gap_pct,
            'volume_ratio': volume_ratio,
            'trend_ok': trend_ok,
            're_stabilize': re_stabilize,
            'window_bars': len(tail),
            'ma5_slope_pct': ma5_slope_pct,
            'ma10_slope_pct': ma10_slope_pct,
            'price_above_prev_high_pct': price_above_prev_high_pct,
            'rebound_strength_pct': rebound_strength_pct,
            'volume_accel_ratio': volume_accel_ratio,
            'recent_green_ratio': recent_green_ratio,
            'breakout_persistence_pct': breakout_persistence_pct,
        })
        return ctx
    except Exception as e:
        logger.error(f'提取信号上下文失败：{e}')
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print('Indicators module OK')
