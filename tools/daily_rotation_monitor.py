#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日 ETF 轮动信号监控器（T+0动量强势策略 - 信号版）

职责：
  - 常驻运行，每个交易日 13:10（贴聚宽原策略时点）触发一次评估
  - 用最新日线 + 13:10 实时价给 27 个候选 ETF 打分
  - 对比"策略目标持仓"与"当前持仓"，生成 BUY/SELL 调仓指令
  - 有调仓指令时推送到企业微信（仅推送信号，不自动下单）
  - 持仓状态持久化到 data/daily_rotation_state.json，重启不丢

注意：
  - 这是【信号监控器】，只推送买卖建议，不连接券商、不实际下单
  - 与 tools/monitor.py（分钟级 T+0 日内监控）完全独立，可并存
  - 与 rotation/run.py（离线回测）共享策略核心 rotation/strategy_momentum.py

用法：
  python tools/daily_rotation_monitor.py start       # 前台运行
  python tools/daily_rotation_monitor.py start-bg    # 后台运行
  python tools/daily_rotation_monitor.py status      # 查看状态
  python tools/daily_rotation_monitor.py stop        # 停止
  python tools/daily_rotation_monitor.py run-once    # 立即跑一次评估（测试用，不等 13:10）
  python tools/daily_rotation_monitor.py dry-run     # 用历史数据模拟今天信号（不发推送）

配置：config/rotation.yaml 的 notify.wechat 段
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Windows 中文乱码修复 + pythonw 后台模式兼容。
# 问题1: cmd.exe 默认 cp936/GBK，输出 UTF-8 中文会乱码 -> 强制 reconfigure 为 utf-8
# 问题2: pythonw.exe 后台模式下 sys.stdout/sys.stderr 可能是 None，
#         直接传给 StreamHandler 会导致写日志时崩溃、进程静默退出。
#         -> 若为 None，替换成丢弃输出的空对象，保证进程不崩。
class _NullStream:
    """空输出流：pythonw 模式下 stdout/stderr 为 None 时的替代，吞掉所有输出。"""
    def write(self, _data): pass
    def flush(self): pass
    def reconfigure(self, *a, **kw): pass

for _name in ('stdout', 'stderr'):
    _stream = getattr(sys, _name, None)
    if _stream is None:
        setattr(sys, _name, _NullStream())
    else:
        try:
            _stream.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
        except Exception:
            pass
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

import yaml

# 路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from rotation import daily_data
from rotation.strategy_momentum import (
    StrategyState, score_etf, check_profit_protection,
    update_range_bound_state, check_realtime_risk_control,
)
from tools.data_fetch import get_fund_realtime
from tools.notifier import send_wechat

CONFIG_PATH = BASE_DIR / 'config' / 'rotation.yaml'
STATE_PATH = BASE_DIR / 'data' / 'daily_rotation_state.json'
SIGNALS_PATH = BASE_DIR / 'data' / 'daily_signals.json'
PID_PATH = BASE_DIR / 'data' / 'daily_rotation_monitor.pid'
HEARTBEAT_PATH = BASE_DIR / 'data' / 'daily_rotation_monitor_heartbeat.json'
LOG_FILE = BASE_DIR / 'logs' / 'daily_rotation_monitor.log'

TRIGGER_TIME = '13:10'  # 每日触发时点（贴聚宽）
MARKET_START = '09:30'
MARKET_END = '15:00'

logger = logging.getLogger('daily_rotation')


# ============================================================
# 配置 & 状态
# ============================================================

def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    """加载持仓状态。结构：
    {
      "holdings": [{"code": "513100", "shares": 46000, "buy_price": 2.16,
                    "buy_date": "2026-06-12", "buy_idx": 638}],
      "last_trigger_date": "2026-06-12",
      "strategy_state": {...}  # StrategyState 序列化
    }
    """
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'holdings': [], 'last_trigger_date': None, 'strategy_state': _default_strategy_state()}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _default_strategy_state() -> dict:
    return {
        'current_filter': '正常期',
        'risk_state': '正常期',
        'previous_rsi': None,
        'previous_drawdown': None,
        'stable_days': 0,
        'last_switch_date': None,
        'range_bound_start_date': None,
        'range_bound_days_count': 0,
    }


def _state_to_obj(s: dict) -> StrategyState:
    return StrategyState(
        current_filter=s.get('current_filter', '正常期'),
        risk_state=s.get('risk_state', '正常期'),
        previous_rsi=s.get('previous_rsi'),
        previous_drawdown=s.get('previous_drawdown'),
        stable_days=s.get('stable_days', 0),
        last_switch_date=pd_ts(s.get('last_switch_date')),
        range_bound_start_date=pd_ts(s.get('range_bound_start_date')),
        range_bound_days_count=s.get('range_bound_days_count', 0),
    )


def pd_ts(s):
    if s is None or s == 'None':
        return None
    try:
        import pandas as pd
        return pd.Timestamp(s)
    except Exception:
        return None


def append_signals(new_signals: list) -> None:
    """追加信号到 data/daily_signals.json，保留最近 200 条。"""
    existing = []
    if SIGNALS_PATH.exists():
        try:
            with open(SIGNALS_PATH, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.extend(new_signals)
    existing = existing[-200:]
    with open(SIGNALS_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# ============================================================
# 信号生成核心
# ============================================================

def evaluate_and_signal(config: dict, dry_run: bool = False, as_of_date: str = None) -> list:
    """执行一次评估，生成调仓信号并（可选）推送。

    dry_run=True: 用历史数据模拟（取 as_of_date 当日收盘价），不推送、不改状态
    as_of_date: dry_run 模式下的评估日期（YYYY-MM-DD），None 则用今天
    返回: 信号列表
    """
    import pandas as pd
    import numpy as np

    etf_pool = config['etf_pool']
    defensive = config.get('defensive_etf')
    benchmark = config.get('benchmark')
    params = config['params']
    notify_cfg = config.get('notify', {})
    holdings_num = int(params.get('holdings_num', 1))

    # ---------- 加载数据 ----------
    all_codes = list(set(etf_pool + ([defensive] if defensive else []) + [benchmark]))
    data = daily_data.load_pool(all_codes, use_cache=True, min_bars=80)
    ok_codes = set(data.keys())
    usable_pool = [c for c in etf_pool if c in ok_codes]

    # ---------- 确定评估日期 & 实时价 ----------
    if dry_run and as_of_date:
        eval_date = pd.Timestamp(as_of_date)
        today_str = eval_date.strftime('%Y-%m-%d')
        realtime_prices = {}  # dry_run 用历史收盘价
    else:
        eval_date = pd.Timestamp(datetime.now().date())
        today_str = eval_date.strftime('%Y-%m-%d')
        # 拉 13:10 实时价（贴聚宽语义）
        realtime_prices = {}
        for code in usable_pool + ([defensive] if defensive and defensive in ok_codes else []):
            rt = get_fund_realtime(code)
            if rt and rt.get('price') and rt['price'] > 0:
                realtime_prices[code] = float(rt['price'])
            time.sleep(0.1)

    # ---------- 加载状态 ----------
    state_dict = load_state()
    # dry_run 时清空持仓，模拟从空仓开始（否则用真实持仓）
    if dry_run:
        state_dict = {'holdings': [], 'last_trigger_date': None,
                      'strategy_state': _default_strategy_state()}
    strategy_state = _state_to_obj(state_dict['strategy_state'])

    # ---------- 对每个标的打分 ----------
    scored = []
    for code in usable_pool:
        df = data[code]
        # 找到评估日对应的 idx（dry_run 用历史日期，实时模式用最后一根）
        if dry_run:
            mask = df['date'] <= eval_date
            if not mask.any():
                continue
            idx = mask.values.nonzero()[0][-1]
            decision_price = float(df['close'].iloc[idx])  # 用当日收盘价模拟
        else:
            idx = len(df) - 1  # 最新一根
            decision_price = realtime_prices.get(code, float(df['close'].iloc[idx]))

        # 涨停跳过
        if idx > 0:
            prev_close = float(df['close'].iloc[idx - 1])
            if decision_price >= prev_close * 1.099:
                continue

        m = score_etf(code, df, idx, params, strategy_state, decision_price=decision_price)
        if m is not None:
            m['realtime_price'] = decision_price
            scored.append(m)

    scored.sort(key=lambda x: x['score'], reverse=True)
    target_codes = [m['code'] for m in scored[:holdings_num]]

    # 无目标 -> 防御
    if not target_codes and defensive and defensive in ok_codes:
        target_codes = [defensive]

    # ---------- 生成调仓信号 ----------
    current_holdings = {h['code']: h for h in state_dict['holdings']}
    target_set = set(target_codes)
    signals = []
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1) 盈利保护卖出（对每个持仓检查）
    for code, holding in current_holdings.items():
        if code not in data:
            continue
        df = data[code]
        if dry_run:
            mask = df['date'] <= eval_date
            if not mask.any():
                continue
            idx = mask.values.nonzero()[0][-1]
        else:
            idx = len(df) - 1
        buy_idx = holding.get('buy_idx', 0)
        if check_profit_protection(code, df, idx, params, buy_idx=buy_idx):
            price = realtime_prices.get(code) if not dry_run else float(df['close'].iloc[idx])
            if price is None:
                price = float(df['close'].iloc[idx])
            profit_pct = (price / holding['buy_price'] - 1) * 100
            signals.append({
                'time': now_str, 'type': 'SELL', 'code': code,
                'reason': '盈利保护(回撤超5%)',
                'price': round(price, 4), 'profit_pct': round(profit_pct, 2),
                'score': None,
            })

    # 2) 轮动卖出（不在目标的持仓）
    for code, holding in current_holdings.items():
        if code in target_set:
            continue
        if code not in data:
            continue
        price = realtime_prices.get(code) if not dry_run else None
        if price is None:
            df = data[code]
            mask = df['date'] <= eval_date if dry_run else slice(None)
            sub = df[mask] if dry_run else df
            if len(sub) == 0:
                continue
            price = float(sub['close'].iloc[-1])
        profit_pct = (price / holding['buy_price'] - 1) * 100
        signals.append({
            'time': now_str, 'type': 'SELL', 'code': code,
            'reason': '轮动调出(动量下降)',
            'price': round(price, 4), 'profit_pct': round(profit_pct, 2),
            'score': None,
        })

    # 3) 买入目标（空仓或换标的）
    for code in target_codes:
        if code in current_holdings:
            continue  # 已持有，不重复买
        if code not in data:
            continue
        price = realtime_prices.get(code) if not dry_run else None
        if price is None:
            df = data[code]
            mask = df['date'] <= eval_date if dry_run else slice(None)
            sub = df[mask] if dry_run else df
            if len(sub) == 0:
                continue
            price = float(sub['close'].iloc[-1])
        score_val = next((m['score'] for m in scored if m['code'] == code), None)
        is_defensive = (code == defensive)
        reason = '防御切换' if is_defensive else f'轮动买入(动量分:{score_val:.3f})' if score_val else '买入'
        signals.append({
            'time': now_str, 'type': 'BUY', 'code': code,
            'reason': reason,
            'price': round(price, 4), 'profit_pct': None,
            'score': round(score_val, 4) if score_val else None,
        })

    # ---------- 更新持仓状态（非 dry_run）----------
    if not dry_run:
        new_holdings = []
        # 卖出的移除
        sold_codes = {s['code'] for s in signals if s['type'] == 'SELL'}
        bought_code = next((s['code'] for s in signals if s['type'] == 'BUY'), None)
        for code, holding in current_holdings.items():
            if code not in sold_codes:
                new_holdings.append(holding)
        # 买入的加入
        if bought_code and bought_code not in current_holdings:
            df = data.get(bought_code)
            idx = len(df) - 1 if df is not None else 0
            buy_price = realtime_prices.get(bought_code) or (float(df['close'].iloc[idx]) if df is not None else 0)
            new_holdings.append({
                'code': bought_code,
                'shares': 'target',  # 信号监控不实际算股数，标记为目标持仓
                'buy_price': buy_price,
                'max_price': buy_price,   # 持仓以来最高价（风控止盈用，会被实时更新）
                'buy_date': today_str,
                'buy_idx': idx,
            })
        # 更新震荡期状态机
        bench_df = data.get(benchmark)
        if bench_df is not None and not bench_df.empty:
            bi = len(bench_df) - 1
            try:
                update_range_bound_state(strategy_state, bench_df, bi, params, eval_date)
            except Exception as e:
                logger.warning(f'震荡期状态更新失败: {e}')
        state_dict['holdings'] = new_holdings
        state_dict['last_trigger_date'] = today_str
        state_dict['strategy_state'] = {
            'current_filter': strategy_state.current_filter,
            'risk_state': strategy_state.risk_state,
            'previous_rsi': strategy_state.previous_rsi,
            'previous_drawdown': strategy_state.previous_drawdown,
            'stable_days': strategy_state.stable_days,
            'last_switch_date': str(strategy_state.last_switch_date) if strategy_state.last_switch_date else None,
            'range_bound_start_date': str(strategy_state.range_bound_start_date) if strategy_state.range_bound_start_date else None,
            'range_bound_days_count': strategy_state.range_bound_days_count,
        }
        save_state(state_dict)

    # ---------- 推送 ----------
    append_signals(signals)
    if signals and not dry_run:
        _push_signals(signals, notify_cfg, scored, today_str)

    return signals


def _push_signals(signals: list, notify_cfg: dict, scored: list, date_str: str) -> None:
    """推送调仓指令到企业微信。"""
    wechat = notify_cfg.get('wechat', {})
    if not wechat.get('enabled'):
        logger.info('企业微信推送未启用，跳过')
        return
    key = wechat.get('key', '')
    if not key:
        logger.warning('企业微信 webhook key 未配置')
        return

    lines = [f'### ETF轮动调仓信号 {date_str} 13:10', '']
    for s in signals:
        emoji = '🟢' if s['type'] == 'BUY' else '🔴'
        profit_str = f'(浮盈{ s["profit_pct"]:+.2f}%)' if s.get('profit_pct') is not None else ''
        lines.append(f'{emoji} **{s["type"]} {s["code"]}** @ {s["price"]} {profit_str}')
        lines.append(f'   {s["reason"]}')
    lines.append('')
    lines.append(f'> 候选池打分前3: ' +
                 ', '.join(f'{m["code"]}({m["score"]:.2f})' for m in scored[:3]) if scored else '> 无达标标的')

    content = '\n'.join(lines)
    ok = send_wechat(key, 'ETF轮动信号', content)
    logger.info(f'企业微信推送: {"成功" if ok else "失败"}')


# ============================================================
# 调度
# ============================================================

def _now_hm() -> str:
    return datetime.now().strftime('%H:%M')


def _today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _is_weekday() -> bool:
    return datetime.now().weekday() < 5  # 0-4 = 周一到周五


def _already_triggered_today(state: dict) -> bool:
    return state.get('last_trigger_date') == _today_str()


def check_realtime_risk(config: dict) -> list:
    """分钟级风控检查（T+0 优势）：对当前持仓拉实时价，检查硬止损/止盈保护。

    触发退出则推送信号并清空持仓。返回触发的信号列表（通常 0 或 1 条）。
    """
    params = config['params']
    rrc = params.get('realtime_risk_control') or {}
    if not rrc.get('enabled', True):
        return []

    state_dict = load_state()
    holdings = state_dict.get('holdings', [])
    if not holdings:
        return []

    signals = []
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    notify_cfg = config.get('notify', {})

    for holding in holdings[:]:
        code = holding.get('code')
        if not code:
            continue
        rt = get_fund_realtime(code)
        if not rt or not rt.get('price') or rt['price'] <= 0:
            continue
        current_price = float(rt['price'])
        buy_price = float(holding.get('buy_price', 0))
        if buy_price <= 0:
            continue

        # 更新持仓最高价
        max_price = float(holding.get('max_price', buy_price))
        if current_price > max_price:
            holding['max_price'] = current_price
            max_price = current_price

        # 临时 holding 字典供 check_realtime_risk_control 使用
        check_holding = {'buy_price': buy_price, 'max_price': max_price}
        reason = check_realtime_risk_control(check_holding, current_price, params)
        if reason is None:
            continue

        pnl_pct = (current_price / buy_price - 1) * 100
        sig = {
            'time': now_str, 'type': 'SELL', 'code': code,
            'reason': reason,
            'price': round(current_price, 4),
            'profit_pct': round(pnl_pct, 2),
            'score': None,
        }
        signals.append(sig)
        logger.info(f'⚡ 风控触发: SELL {code} @ {current_price} - {reason} (盈亏{pnl_pct:+.2f}%)')

        # 清除持仓
        holdings.remove(holding)

    if signals:
        state_dict['holdings'] = holdings
        save_state(state_dict)
        append_signals(signals)
        _push_signals(signals, notify_cfg, [], _today_str())

    return signals


def run_loop() -> None:
    """常驻主循环：
    - 每分钟：对持仓做风控检查（硬止损/止盈保护，T+0 优势）
    - 13:10：日频轮动评估（打分选股 → 调仓信号）
    """
    logger.info('=' * 60)
    logger.info(f'轮动信号+风控监控器启动 (PID {os.getpid()})')
    logger.info(f'  日频轮动：每个交易日 {TRIGGER_TIME} 选股一次')
    logger.info(f'  分钟风控：交易时段 {MARKET_START}~{MARKET_END} 每 30 秒检查硬止损/止盈')
    logger.info(f'  非交易时段（午休/收盘后/周末）：每 60 秒心跳，不退出')
    logger.info('=' * 60)
    write_heartbeat('running', {'phase': 'started'})
    last_risk_check = 0
    last_idle_log = 0       # 控制非交易时段日志频率（每 5 分钟一次）
    last_monitor_log = 0    # 控制交易时段常规日志频率（每 5 分钟一次）
    while True:
        try:
            now = _now_hm()
            now_ts = time.time()

            # ---------- 非交易时段：心跳，不退出 ----------
            if not (_is_weekday() and MARKET_START <= now <= MARKET_END):
                # 每 5 分钟输出一次可读日志（证明进程活着）
                if now_ts - last_idle_log >= 300:
                    reason = '周末/节假日' if not _is_weekday() else '非交易时段'
                    holdings = load_state().get('holdings', [])
                    logger.info(f'[待机] {reason} {now} | 持仓 {len(holdings)} 只 | 进程持续运行中')
                    last_idle_log = now_ts
                write_heartbeat('idle', {'phase': 'non_market_hours'})
                time.sleep(60)
                continue

            # ---------- 交易时段 ----------
            config = load_config()
            holdings = load_state().get('holdings', [])

            # 1) 分钟级风控检查（每 30 秒一次）
            if now_ts - last_risk_check >= 30:
                if holdings:
                    risk_signals = check_realtime_risk(config)
                    last_risk_check = now_ts
                    if risk_signals:
                        logger.info(f'⚡ 风控触发 {len(risk_signals)} 条信号')
                    elif now_ts - last_monitor_log >= 300:
                        # 每 5 分钟输出一次"风控正常"心跳
                        logger.info(f'[风控] {now} 持仓 {len(holdings)} 只，价格正常')
                        last_monitor_log = now_ts
                else:
                    last_risk_check = now_ts  # 空仓也要更新，避免持仓后立即高频检查

            # 2) 日频轮动（13:10 触发一次）
            state = load_state()
            if now >= TRIGGER_TIME and not _already_triggered_today(state):
                logger.info(f'=== 触发每日轮动评估 ({_today_str()} {now}) ===')
                signals = evaluate_and_signal(config)
                if signals:
                    logger.info(f'轮动信号 {len(signals)} 条: ' +
                                ', '.join(f'{s["type"]}{s["code"]}' for s in signals))
                else:
                    logger.info('今日无轮动调仓信号（持仓不变）')
                write_heartbeat('running', {'last_eval': _today_str() + ' ' + now,
                                            'last_signals': len(signals)})

            write_heartbeat('running', {'phase': 'monitoring', 'holdings': len(holdings)})
            time.sleep(10)  # 主循环 10 秒一轮，风控检查内部用 last_risk_check 控制为 30 秒
        except KeyboardInterrupt:
            logger.info('收到中断信号，退出')
            break
        except Exception as e:
            logger.error(f'主循环异常: {e}', exc_info=True)
            write_heartbeat('error', {'msg': str(e)})
            time.sleep(60)


# ============================================================
# 进程管理
# ============================================================

def write_heartbeat(status: str, extra: dict = None) -> None:
    hb = {'status': status, 'pid': os.getpid(),
          'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    if extra:
        hb.update(extra)
    try:
        with open(HEARTBEAT_PATH, 'w', encoding='utf-8') as f:
            json.dump(hb, f, ensure_ascii=False)
    except Exception:
        pass


def save_pid(pid: int) -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PID_PATH, 'w') as f:
        f.write(str(pid))


def load_pid() -> int | None:
    if PID_PATH.exists():
        try:
            return int(PID_PATH.read_text().strip())
        except Exception:
            return None
    return None


def is_running() -> bool:
    pid = load_pid()
    if pid is None:
        return False
    # 注意：os.kill(pid, 0) 在 Windows 上不可靠（用 TerminateProcess 实现，
    # 对某些 PID 会抛 WinError 87），改用 tasklist 探测。
    if os.name == 'nt':
        try:
            # tasklist 在中文 Windows 输出 GBK，需指定编码避免 UnicodeDecodeError
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
                capture_output=True, timeout=5, encoding='gbk', errors='replace')
            # 输出含 PID 说明进程存在；"信息: 没有运行的任务..."说明不存在
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError, SystemError):
            return False


def cmd_start_bg() -> int:
    if is_running():
        print(f'监控器已在运行 (PID {load_pid()})')
        return 0
    python = sys.executable
    cmd = [python, str(Path(__file__).resolve()), 'run-loop']
    log_fp = open(LOG_FILE, 'a', encoding='utf-8')
    kwargs = dict(
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
    )
    if os.name == 'nt':
        # Windows：新进程组，关闭终端不影响
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # Linux/macOS：新会话，脱离控制终端（关闭 ssh 不杀进程）
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    log_fp.close()  # 子进程已继承 fd，父进程关闭自己的句柄
    save_pid(proc.pid)
    print(f'监控器已后台启动 (PID {proc.pid})，触发时点 {TRIGGER_TIME}')
    print(f'日志: {LOG_FILE}')
    return 0


def cmd_stop() -> int:
    pid = load_pid()
    if pid is None:
        print('监控器未运行')
        return 0
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
        else:
            os.kill(pid, 15)
        print(f'已停止监控器 (PID {pid})')
    except Exception as e:
        print(f'停止失败: {e}')
    try:
        PID_PATH.unlink()
    except Exception:
        pass
    return 0


def cmd_status() -> int:
    pid = load_pid()
    running = is_running()
    print(f'运行状态: {"运行中" if running else "已停止"}')
    if pid:
        print(f'PID: {pid}')
    state = load_state()
    print(f'上次触发: {state.get("last_trigger_date", "无")}')
    print(f'当前持仓: {state.get("holdings", [])}')
    if HEARTBEAT_PATH.exists():
        try:
            hb = json.loads(HEARTBEAT_PATH.read_text(encoding='utf-8'))
            print(f'心跳: {hb.get("time")} ({hb.get("status")})')
        except Exception:
            pass
    return 0


# ============================================================
# CLI
# ============================================================

def setup_logging():
    # UTF-8 处理已在文件顶部完成（影响所有 import 阶段的输出）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
                  logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(description='每日 ETF 轮动信号监控器')
    parser.add_argument('cmd', choices=['start', 'start-bg', 'stop', 'status',
                                        'run-loop', 'run-once', 'dry-run'])
    parser.add_argument('--date', default=None, help='dry-run 模式的评估日期 YYYY-MM-DD')
    args = parser.parse_args()

    setup_logging()

    if args.cmd == 'start':
        # 前台运行
        run_loop()
    elif args.cmd == 'start-bg':
        sys.exit(cmd_start_bg())
    elif args.cmd == 'stop':
        sys.exit(cmd_stop())
    elif args.cmd == 'status':
        sys.exit(cmd_status())
    elif args.cmd == 'run-loop':
        run_loop()
    elif args.cmd == 'run-once':
        # 立即跑一次评估（不等 13:10，会推送）
        config = load_config()
        signals = evaluate_and_signal(config)
        print(f'生成 {len(signals)} 条信号:')
        for s in signals:
            print(f'  {s["type"]} {s["code"]} @ {s["price"]} - {s["reason"]}')
    elif args.cmd == 'dry-run':
        # 用历史数据模拟，不推送、不改状态
        config = load_config()
        if not args.date:
            # 默认用最近一个交易日
            data = daily_data.load_pool(config['etf_pool'][:3], use_cache=True, min_bars=10)
            df = next(iter(data.values()))
            args.date = str(df['date'].iloc[-1].date())
            print(f'未指定 --date，使用最近交易日: {args.date}')
        signals = evaluate_and_signal(config, dry_run=True, as_of_date=args.date)
        print(f'\n=== dry-run 模拟 ({args.date}) ===')
        print(f'生成 {len(signals)} 条信号（不推送、不改状态）:')
        for s in signals:
            print(f'  {s["type"]} {s["code"]} @ {s["price"]} - {s["reason"]}')


if __name__ == '__main__':
    main()
