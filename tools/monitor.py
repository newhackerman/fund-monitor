#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T+0 基金实时监控 - 健壮版（带日志、重试、进程守护）"""

import os
import sys
import json
import yaml
import time
import argparse
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from apscheduler.schedulers.background import BackgroundScheduler


def _configure_runtime_compat():
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('PYTHONLEGACYWINDOWSSTDIO', '0')
    if os.name == 'nt':
        try:
            import locale
            locale.getpreferredencoding = lambda do_setlocale=True: 'UTF-8'
        except Exception:
            pass
        try:
            os.system('chcp 65001 >nul 2>nul')
        except Exception:
            pass
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass


_configure_runtime_compat()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetch import _get_tencent_realtime as get_fund_realtime, get_fund_1min_kline
from indicators import calculate_indicators, extract_signal_context
from signals import generate_signals, process_signal, load_trades, rank_new_buy_signals
from notifier import notify

BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = BASE_DIR / 'data'
CONFIG_DIR = BASE_DIR / 'config'
LOGS_DIR = BASE_DIR / 'logs'
LOG_FILE = LOGS_DIR / 'monitor.log'
STDOUT_LOG_FILE = LOGS_DIR / 'monitor_stdout.log'
STARTUP_LOG_FILE = LOGS_DIR / 'monitor_startup.log'
WATCHLIST_FILE = DATA_DIR / 'watchlist.json'
SIGNALS_FILE = DATA_DIR / 'signals.json'
CONFIG_FILE = CONFIG_DIR / 'default.yaml'
PID_FILE = DATA_DIR / 'monitor.pid'
HEARTBEAT_FILE = DATA_DIR / 'monitor_heartbeat.json'
KEEPALIVE_PID_FILE = DATA_DIR / 'monitor_keepalive.pid'
STATS_EXPORT_SCRIPT = BASE_DIR.parent / 'scripts' / 'fund_monitor_export_stats_snapshot.py'
for d in [DATA_DIR, CONFIG_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

scheduler = None
monitoring = False
fast_mode = False
shutdown_requested = False


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


logger = setup_logging()


def _append_startup_log(message: str):
    try:
        with open(STARTUP_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}\n")
    except Exception:
        pass


def write_heartbeat(status: str = 'running', extra: dict | None = None):
    payload = {
        'pid': os.getpid(),
        'status': status,
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ts': time.time(),
    }
    if extra:
        payload.update(extra)
    try:
        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_heartbeat() -> dict | None:
    try:
        if HEARTBEAT_FILE.exists():
            with open(HEARTBEAT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        return None
    return None


def _is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == 'nt':
            result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=5, check=False)
            out = (result.stdout or '').strip()
            return str(pid) in out and 'No tasks are running' not in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def get_running_pid():
    try:
        hb = load_heartbeat() or {}
        pid_from_file = None
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r', encoding='utf-8') as f:
                pid_from_file = int(f.read().strip())
        candidates = [pid_from_file, hb.get('pid')]
        for pid in candidates:
            if isinstance(pid, int) and _is_pid_alive(pid):
                return pid
        return None
    except Exception:
        return None


def _clear_runtime_markers():
    for path in (PID_FILE, HEARTBEAT_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _cleanup_stale_pid():
    pid = get_running_pid()
    hb = load_heartbeat() or {}
    hb_pid = hb.get('pid')
    if pid is None and not (isinstance(hb_pid, int) and _is_pid_alive(hb_pid)):
        _clear_runtime_markers()


def signal_handler(signum, frame):
    global shutdown_requested, monitoring, scheduler
    logger.info(f'收到信号 {signum}，准备退出...')
    write_heartbeat('stopping', {'phase': 'signal_handler', 'signum': signum})
    shutdown_requested = True
    monitoring = False
    try:
        if scheduler:
            scheduler.shutdown(wait=False)
            scheduler = None
    except Exception:
        pass
    _clear_runtime_markers()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def save_pid():
    with open(PID_FILE, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))


def load_config() -> dict:
    default_config = {
        'monitor': {
            'interval': 60,
            'market_hours': {'start': '09:30', 'end': '15:00', 'noon_break': {'start': '11:30', 'end': '13:00'}},
            'fast_mode': False,
            'warmup_on_start': True,
            'warmup_periods_1m': 240,
        },
        'indicators': {'macd': {'fast': 12, 'slow': 26, 'signal': 9}, 'rsi': {'period': 14}, 'atr': {'period': 14}},
        'signals': {'cooldown_minutes': 60, 'max_new_buys_per_cycle': 3},
        'notify': {'dingtalk': {'enabled': False, 'webhook': ''}, 'wechat': {'enabled': False, 'key': ''}, 'terminal': {'enabled': True, 'sound': True}},
    }
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
                if user_config:
                    for key in user_config:
                        if isinstance(user_config[key], dict) and key in default_config:
                            default_config[key].update(user_config[key])
                        else:
                            default_config[key] = user_config[key]
    except Exception as e:
        logger.error(f'加载配置失败：{e}')
    return default_config


def load_watchlist() -> list:
    try:
        if WATCHLIST_FILE.exists():
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        logger.error(f'加载监控列表失败：{e}')
    return []


def load_signals(today_only: bool = False) -> list:
    try:
        if SIGNALS_FILE.exists():
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                if not today_only:
                    return data
                today = datetime.now().strftime('%Y-%m-%d')
                return [item for item in data if str(item.get('time') or '').startswith(today)]
    except Exception as e:
        logger.error(f'加载信号失败：{e}')
    return []


def append_signals(new_signals: list, keep: int = 200):
    try:
        if not new_signals:
            return
        signals = load_signals(today_only=True)
        merged = signals + list(new_signals)
        deduped = []
        seen = set()
        for item in merged:
            key = (
                item.get('type'),
                item.get('code'),
                item.get('time'),
                str(item.get('price')),
                item.get('reason'),
                item.get('status'),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped = deduped[-keep:]
        with open(SIGNALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(deduped, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f'保存信号失败：{e}')


def is_market_hours() -> bool:
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        config = load_config()
        market = config['monitor']['market_hours']
        if now.weekday() >= 5:
            return False
        if current_time < market['start'] or current_time >= market['end']:
            return False
        noon = market['noon_break']
        if noon['start'] <= current_time < noon['end']:
            return False
        return True
    except Exception as e:
        logger.error(f'判断交易时间失败：{e}')
        return False


def _dedupe_signals_today(signals: list, cooldown_minutes: int = 20) -> list:
    if not signals:
        return []
    today = datetime.now().strftime('%Y-%m-%d')
    kept = []
    last_seen = {}
    for s in sorted(signals, key=lambda x: str(x.get('time', ''))):
        ts = str(s.get('time') or '')
        if not ts.startswith(today):
            continue
        key = (s.get('code'), s.get('type'))
        try:
            cur = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            prev = last_seen.get(key)
            if prev and (cur - prev).total_seconds() < cooldown_minutes * 60:
                continue
            last_seen[key] = cur
        except Exception:
            pass
        kept.append(s)
    return kept


def export_stats_snapshot():
    try:
        if not STATS_EXPORT_SCRIPT.exists():
            return
        subprocess.run([sys.executable, str(STATS_EXPORT_SCRIPT)], cwd=str(BASE_DIR.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception as e:
        logger.warning(f'导出 stats_snapshot 失败：{e}')


def log_5min_summary(total_count: int, success_count: int, signal_count: int):
    try:
        now = datetime.now()
        if now.minute % 5 != 0 or now.second > 20:
            return
        running_pid = get_running_pid()
        logger.info(f"5分钟运行摘要 | 时间：{now.strftime('%H:%M:%S')} | 状态：{'运行中' if running_pid else '已停止'} | 成功：{success_count}/{total_count} | 新信号：{signal_count} | PID：{running_pid or '-'}")
    except Exception as e:
        logger.error(f'输出 5 分钟摘要失败：{e}')


def warmup_cache(config: dict, watchlist: list):
    periods = int(config.get('monitor', {}).get('warmup_periods_1m', 240) or 240)
    logger.info(f'开始预热分钟缓存：{len(watchlist)} 只，目标 {periods} 根 1m')
    ok = 0
    for code in watchlist:
        try:
            df = get_fund_1min_kline(code, periods=periods)
            if df is not None and len(df) > 0:
                ok += 1
        except Exception as e:
            logger.warning(f'预热失败 {code}: {e}')
    logger.info(f'预热完成：{ok}/{len(watchlist)}')


def check_single_fund(code: str, config: dict, use_fast_mode: bool = False) -> list:
    results = []
    try:
        realtime = get_fund_realtime(code)
        if not realtime:
            return None
        kline = get_fund_1min_kline(code, periods=240)
        if kline is None or len(kline) == 0:
            return None
        kline_with_indicators = calculate_indicators(kline, config.get('indicators'), fast_mode=False)
        if kline_with_indicators is None:
            return None
        context = extract_signal_context(kline_with_indicators, lookback=25)
        if context is None:
            return None
        fund_signals = generate_signals(code, realtime['name'], context, config.get('signals'), fast_mode=False)
        cooldown = int((config.get('signals') or {}).get('cooldown_minutes', 60) or 60)
        fund_signals = _dedupe_signals_today(fund_signals, cooldown_minutes=cooldown)
        for sig in fund_signals:
            sig['realtime'] = realtime
            results.append({'signal': sig, 'realtime': realtime})
        return results
    except Exception as e:
        logger.error(f'检查基金 {code} 失败：{e}', exc_info=True)
        return None


def run_check():
    global fast_mode
    try:
        write_heartbeat('running', {'phase': 'run_check_enter'})
        if not is_market_hours():
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 非交易时间，跳过")
            write_heartbeat('idle', {'phase': 'non_market_hours'})
            return
        config = load_config()
        watchlist = load_watchlist()
        fast_mode = config['monitor'].get('fast_mode', False)
        mode_str = '快速' if fast_mode else '标准'
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] {mode_str} - 检查 {len(watchlist)} 只基金...")
        raw_results = []
        success_count = 0
        for code in watchlist:
            results = check_single_fund(code, config, use_fast_mode=fast_mode)
            if results is not None:
                success_count += 1
                if results:
                    raw_results.extend(results)

        raw_signals = [r['signal'] for r in raw_results]
        ranked_signals = rank_new_buy_signals(raw_signals, config.get('signals'))
        ranked_keys = {(s['code'], s['type'], s['time']) for s in ranked_signals}
        new_results = [r for r in raw_results if (r['signal']['code'], r['signal']['type'], r['signal']['time']) in ranked_keys]

        dropped = [s for s in raw_signals if (s['code'], s['type'], s['time']) not in ranked_keys and s.get('type') == 'BUY']
        if dropped:
            logger.info(f'本轮买入候选 {len([s for s in raw_signals if s.get("type") == "BUY"])} 个，限流后保留 {len([s for s in ranked_signals if s.get("type") == "BUY"])} 个')
            for s in dropped[:10]:
                logger.info(f'   丢弃 BUY {s["code"]} @ {s["time"][11:19]}')

        if new_results:
            processed_results = []
            for item in new_results:
                signal = item['signal']
                result = process_signal(signal)
                processed_results.append(result)
                notify(signal, config)
                if result['profit']:
                    profit_pct = result['profit']['profit_pct']
                    profit_emoji = '+' if profit_pct > 0 else '-'
                    logger.info(f'{profit_emoji} 完成交易！盈亏：{profit_pct:+.2f}% - {signal["code"]}')
            append_signals([r['signal'] for r in processed_results])
            export_stats_snapshot()
            logger.info(f'发现 {len(processed_results)} 个新信号!')
        else:
            export_stats_snapshot()
            logger.info('无新信号')
        logger.info(f'检查完成 - 成功：{success_count}/{len(watchlist)}')
        write_heartbeat('running', {'phase': 'run_check_done', 'watchlist_count': len(watchlist), 'success_count': success_count, 'signal_count': len(new_results)})
        log_5min_summary(len(watchlist), success_count, len(new_results))
    except Exception as e:
        write_heartbeat('error', {'phase': 'run_check_error', 'error': str(e)})
        logger.error(f'监控检查失败：{e}', exc_info=True)


def _main_loop():
    while monitoring and not shutdown_requested:
        write_heartbeat('running', {'phase': 'main_loop'})
        time.sleep(1)


def cmd_start(args):
    global scheduler, monitoring, fast_mode, shutdown_requested
    try:
        _cleanup_stale_pid()
        if get_running_pid():
            logger.info(f'监控已在运行中 (PID: {get_running_pid()})')
            return
        _append_startup_log('cmd_start entered')
        _append_startup_log(f'argv={sys.argv}')
        watchlist = load_watchlist()
        if not watchlist:
            logger.info('监控列表为空')
            return
        shutdown_requested = False
        config = load_config()
        interval = config['monitor']['interval']
        fast_mode = config['monitor'].get('fast_mode', False)
        skip_warmup = bool(getattr(args, 'skip_warmup', False))
        if config['monitor'].get('warmup_on_start', True) and not skip_warmup:
            warmup_cache(config, watchlist)
        elif skip_warmup:
            logger.info('后台启动模式：跳过启动预热，首轮检查时再逐步建立缓存')
        _append_startup_log('about to create BackgroundScheduler daemon=False')
        scheduler = BackgroundScheduler(daemon=False)
        scheduler.add_job(run_check, 'interval', seconds=interval, max_instances=1, coalesce=True)
        scheduler.start()
        _append_startup_log('scheduler.start() ok')
        monitoring = True
        save_pid()
        _append_startup_log(f'save_pid ok pid={os.getpid()} path={PID_FILE}')
        write_heartbeat('starting', {'phase': 'scheduler_started', 'skip_warmup': skip_warmup})
        _append_startup_log(f'write_heartbeat starting ok path={HEARTBEAT_FILE}')
        _append_startup_log(f'scheduler started pid={os.getpid()} skip_warmup={skip_warmup}')
        mode_str = '快速模式 (1 分钟)' if fast_mode else '标准模式 (窗口特征)'
        logger.info(f'监控已启动 - {mode_str}')
        logger.info(f'监控基金：{len(watchlist)}只')
        logger.info(f'检查间隔：{interval}秒')
        logger.info('交易时间：09:30-11:30, 13:00-15:00')
        logger.info(f'日志文件：{LOG_FILE}')
        logger.info(f'PID: {os.getpid()}')
        logger.info('\n按 Ctrl+C 停止监控')
        _append_startup_log('enter _main_loop')
        _main_loop()
        _append_startup_log('_main_loop returned')
    except Exception as e:
        write_heartbeat('error', {'phase': 'cmd_start_error', 'error': str(e)})
        _append_startup_log(f'cmd_start_error: {e}')
        logger.error(f'启动失败：{e}', exc_info=True)
    finally:
        _append_startup_log(f'cmd_start finally shutdown_requested={shutdown_requested} monitoring={monitoring}')
        if shutdown_requested:
            cmd_stop(args)
        else:
            _append_startup_log('cmd_start exited without shutdown_requested')


def _wait_for_background_ready(timeout_seconds: int = 45, interval_seconds: float = 1.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        pid = get_running_pid()
        hb = load_heartbeat() or {}
        if pid and hb.get('pid') == pid and hb.get('status') in {'starting', 'running', 'idle'}:
            return pid, hb
        time.sleep(interval_seconds)
    return None, load_heartbeat()


def _build_start_command_for_background() -> list:
    # Windows 下优先拉起 keepalive，由守护进程负责托管 worker，避免后台 worker 异常退出后无人拉起。
    if os.name == 'nt':
        return [sys.executable, os.path.abspath(__file__), 'keepalive']
    return [sys.executable, os.path.abspath(__file__), 'start', '--skip-warmup']


def cmd_keepalive(args):
    global shutdown_requested
    restart_delay = 5
    existing_keepalive = None
    try:
        if KEEPALIVE_PID_FILE.exists():
            existing_keepalive = int(KEEPALIVE_PID_FILE.read_text(encoding='utf-8').strip())
    except Exception:
        existing_keepalive = None
    if existing_keepalive and existing_keepalive != os.getpid() and _is_pid_alive(existing_keepalive):
        logger.info(f'keepalive 已在运行中 (PID: {existing_keepalive})')
        _append_startup_log(f'cmd_keepalive skipped duplicate pid={existing_keepalive}')
        return
    try:
        with open(KEEPALIVE_PID_FILE, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    logger.info('keepalive 守护模式已启动')
    _append_startup_log(f'cmd_keepalive entered pid={os.getpid()}')
    while not shutdown_requested:
        try:
            child_pid = get_running_pid()
            if child_pid and _is_pid_alive(child_pid):
                _append_startup_log(f'keepalive found running child pid={child_pid}, wait 5s')
                time.sleep(restart_delay)
                continue
            _append_startup_log('keepalive launching child start --skip-warmup')
            proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), 'start', '--skip-warmup'], cwd=str(BASE_DIR))
            _append_startup_log(f'keepalive child pid={proc.pid}')
            code = proc.wait()
            _append_startup_log(f'keepalive child exited code={code}')
            if shutdown_requested:
                break
            logger.warning(f'监控子进程已退出，{restart_delay} 秒后尝试重启，exit_code={code}')
        except KeyboardInterrupt:
            shutdown_requested = True
            _append_startup_log('cmd_keepalive keyboard interrupt')
            break
        except Exception as e:
            _append_startup_log(f'cmd_keepalive error: {e}')
            logger.error(f'keepalive 守护失败：{e}', exc_info=True)
        if not shutdown_requested:
            time.sleep(restart_delay)
    try:
        if KEEPALIVE_PID_FILE.exists() and KEEPALIVE_PID_FILE.read_text(encoding='utf-8').strip() == str(os.getpid()):
            KEEPALIVE_PID_FILE.unlink()
    except Exception:
        pass


def cmd_start_bg(args):
    stdout_fp = None
    stderr_fp = None
    try:
        _cleanup_stale_pid()
        running_pid = get_running_pid()
        keepalive_pid = None
        try:
            if KEEPALIVE_PID_FILE.exists():
                keepalive_pid = int(KEEPALIVE_PID_FILE.read_text(encoding='utf-8').strip())
                if not _is_pid_alive(keepalive_pid):
                    keepalive_pid = None
        except Exception:
            keepalive_pid = None
        if running_pid or keepalive_pid:
            logger.info(f"监控已在运行中 (worker={running_pid or '-'}, keepalive={keepalive_pid or '-'})")
            return
        _append_startup_log('cmd_start_bg entered')
        cmd = _build_start_command_for_background()
        stdout_fp = open(STDOUT_LOG_FILE, 'a', encoding='utf-8')
        stderr_fp = open(STDOUT_LOG_FILE, 'a', encoding='utf-8')
        kwargs = {
            'cwd': str(BASE_DIR),
            'stdout': stdout_fp,
            'stderr': stderr_fp,
            'stdin': subprocess.DEVNULL,
        }
        if os.name == 'nt':
            kwargs['creationflags'] = (
                getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                | getattr(subprocess, 'DETACHED_PROCESS', 0)
                | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            )
            kwargs['close_fds'] = False
        else:
            kwargs['start_new_session'] = True

        proc = subprocess.Popen(cmd, **kwargs)
        _append_startup_log(f'launcher_pid={proc.pid} cmd={cmd}')
        _append_startup_log(f'cmd_start_bg cwd={BASE_DIR} stdout_log={STDOUT_LOG_FILE}')
        logger.info(f'已发起后台启动，请等待 PID / heartbeat 落盘... launcher_pid={proc.pid}')

        pid, hb = _wait_for_background_ready(timeout_seconds=45, interval_seconds=1.0)
        if pid:
            logger.info(f'后台监控已启动 (PID: {pid})')
            logger.info(f'输出日志：{STDOUT_LOG_FILE}')
            logger.info(f'启动日志：{STARTUP_LOG_FILE}')
            logger.info(f'心跳状态：{hb.get("status")} | phase={hb.get("phase", "-")}')
            return

        logger.warning('后台启动后 45 秒内仍未确认 PID / heartbeat。')
        logger.warning(f'请查看日志：{STDOUT_LOG_FILE}')
        logger.warning(f'请查看启动日志：{STARTUP_LOG_FILE}')
        if hb:
            logger.warning(f'最近心跳：status={hb.get("status")} phase={hb.get("phase")} error={hb.get("error", "-")}')
    except Exception as e:
        _append_startup_log(f'cmd_start_bg_error: {e}')
        logger.error(f'后台启动失败：{e}', exc_info=True)
    finally:
        for fp in (stdout_fp, stderr_fp):
            if fp:
                try:
                    fp.close()
                except Exception:
                    pass


def cmd_stop(args):
    global scheduler, monitoring, shutdown_requested
    try:
        pid = get_running_pid()
        keepalive_pid = None
        try:
            if KEEPALIVE_PID_FILE.exists():
                keepalive_pid = int(KEEPALIVE_PID_FILE.read_text(encoding='utf-8').strip())
                if not _is_pid_alive(keepalive_pid):
                    keepalive_pid = None
        except Exception:
            keepalive_pid = None
        targets = []
        if pid and pid != os.getpid():
            targets.append(pid)
        if keepalive_pid and keepalive_pid != os.getpid() and keepalive_pid not in targets:
            targets.append(keepalive_pid)
        for target_pid in targets:
            try:
                os.kill(target_pid, signal.SIGTERM)
                time.sleep(1)
            except Exception:
                pass
        for _ in range(10):
            still_running = [x for x in targets if _is_pid_alive(x)]
            if not still_running:
                break
            time.sleep(0.5)
        if scheduler:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            scheduler = None
        monitoring = False
        shutdown_requested = True
        write_heartbeat('stopped', {'phase': 'cmd_stop'})
        _clear_runtime_markers()
        try:
            if KEEPALIVE_PID_FILE.exists():
                KEEPALIVE_PID_FILE.unlink()
        except Exception:
            pass
        logger.info('监控已停止')
    except Exception as e:
        logger.error(f'停止失败：{e}')


def cmd_status(args):
    try:
        _cleanup_stale_pid()
        watchlist = load_watchlist()
        trades = load_trades()
        open_positions = [t for t in trades if t.get('status') == 'OPEN']
        stale_positions = [t for t in trades if t.get('type') == 'BUY' and t.get('status') == 'OPEN' and str(t.get('time', ''))[:10] and str(t.get('time', ''))[:10] != datetime.now().strftime('%Y-%m-%d')]
        closed_trades = [t for t in trades if t.get('status') == 'CLOSED' and t['type'] == 'SELL']
        logger.info('监控状态')
        logger.info('=' * 50)
        logger.info(f'监控基金：{len(watchlist)}只')
        logger.info(f'总交易：{len(trades)} | 未平仓：{len(open_positions)} | 跨日OPEN仓：{len(stale_positions)} | 已完成：{len(closed_trades)}')
        running_pid = get_running_pid()
        hb = load_heartbeat() or {}
        keepalive_pid = None
        try:
            if KEEPALIVE_PID_FILE.exists():
                keepalive_pid = int(KEEPALIVE_PID_FILE.read_text(encoding='utf-8').strip())
                if not _is_pid_alive(keepalive_pid):
                    keepalive_pid = None
        except Exception:
            keepalive_pid = None
        logger.info(f"运行状态：{'运行中' if (running_pid or keepalive_pid) else '已停止'}")
        if running_pid:
            logger.info(f'进程 PID: {running_pid}')
        if keepalive_pid:
            logger.info(f'守护 PID: {keepalive_pid}')
        if hb:
            logger.info(f"心跳：status={hb.get('status')} | phase={hb.get('phase', '-')} | time={hb.get('time')}")
        if stale_positions:
            logger.warning(f'\n检测到 {len(stale_positions)} 条跨日 OPEN 仓位，未自动改动，请按真实持仓核对。')
        if closed_trades:
            total_profit = sum(float(t['profit_pct']) for t in closed_trades)
            winning = sum(1 for t in closed_trades if float(t['profit_pct']) > 0)
            losses = [float(t['profit_pct']) for t in closed_trades if float(t['profit_pct']) < 0]
            wins = [float(t['profit_pct']) for t in closed_trades if float(t['profit_pct']) > 0]
            payoff = (sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else 0.0
            logger.info(f'\n表现（trades.json）：胜率 {winning/len(closed_trades)*100:.2f}% | 盈亏比 {payoff:.2f} | 累计 {total_profit:+.2f}%')
        logger.info(f'启动日志：{STARTUP_LOG_FILE}')
        logger.info(f'心跳文件：{HEARTBEAT_FILE}')
    except Exception as e:
        logger.error(f'显示状态失败：{e}')


def main():
    parser = argparse.ArgumentParser(description='T+0 基金实时监控')
    subparsers = parser.add_subparsers(dest='command')
    p_start = subparsers.add_parser('start', help='启动监控')
    p_start.add_argument('--skip-warmup', action='store_true', help='跳过启动预热，适合后台快速拉起')
    p_start.set_defaults(func=cmd_start)
    subparsers.add_parser('start-bg', help='后台启动监控').set_defaults(func=cmd_start_bg)
    subparsers.add_parser('keepalive', help='守护模式：子进程退出后自动重启').set_defaults(func=cmd_keepalive)
    subparsers.add_parser('stop', help='停止监控').set_defaults(func=cmd_stop)
    subparsers.add_parser('status', help='监控状态').set_defaults(func=cmd_status)
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()
