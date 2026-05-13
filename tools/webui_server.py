from __future__ import annotations

import json
import os
import subprocess
from collections import Counter, defaultdict
from contextlib import suppress
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
LOGS_DIR = ROOT / 'logs'
MINUTE_CACHE_DIR = DATA_DIR / 'minute_cache'
PID_FILE = DATA_DIR / 'monitor.pid'
KEEPALIVE_PID_FILE = DATA_DIR / 'monitor_keepalive.pid'
HEARTBEAT_FILE = DATA_DIR / 'monitor_heartbeat.json'
WATCHLIST_FILE = DATA_DIR / 'watchlist.json'
SIGNALS_FILE = DATA_DIR / 'signals.json'
TRADES_FILE = DATA_DIR / 'trades.json'
INDEX_FILE = Path(__file__).resolve().parent / 'webui' / 'index.html'
LOG_LINES_LIMIT = 80


def read_json(path: Path, default: Any):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == 'nt':
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            out = (result.stdout or '').strip()
            return str(pid) in out and 'No tasks are running' not in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def read_heartbeat() -> dict:
    hb = read_json(HEARTBEAT_FILE, {})
    return hb if isinstance(hb, dict) else {}


def latest_trading_day(items: list[dict]) -> str | None:
    days = sorted({str(x.get('time', ''))[:10] for x in items if str(x.get('time', ''))[:10]})
    return days[-1] if days else None


def build_open_positions(items: list[dict], day: str | None):
    rows = [x for x in items if (not day or str(x.get('time', '')).startswith(day))]
    rows.sort(key=lambda x: str(x.get('time', '')))
    state: dict[str, dict] = {}
    for x in rows:
        code = str(x.get('code', '') or '')
        if not code:
            continue
        typ = x.get('type')
        status = str(x.get('status', '') or '')
        if typ == 'BUY':
            state[code] = x
        elif typ == 'SELL' or status == 'CLOSED':
            state.pop(code, None)
    return list(state.values())


def _build_day_view(items: list[dict], day: str | None):
    rows = []
    open_state: dict[str, dict] = {}
    buy_count = 0
    closed_count = 0
    wins = 0
    profit_sum = 0.0

    for x in items:
        t = str(x.get('time', '') or '')
        if day and not t.startswith(day):
            continue
        rows.append(x)
        code = str(x.get('code', '') or '')
        typ = x.get('type')
        status = str(x.get('status', '') or '')

        if typ == 'BUY':
            buy_count += 1
            if code:
                open_state[code] = x
        if typ == 'SELL':
            closed_count += 1
            try:
                profit = float(x.get('profit_pct', 0) or 0)
            except Exception:
                profit = 0.0
            profit_sum += profit
            if profit > 0:
                wins += 1
        if (typ == 'SELL' or status == 'CLOSED') and code:
            open_state.pop(code, None)

    closed_profits = closed_count
    return {
        'rows': rows,
        'open_positions': list(open_state.values()),
        'metrics': {
            'trade_count': buy_count,
            'closed_count': closed_count,
            'open_count': len(open_state),
            'win_rate': round(wins / closed_profits * 100, 2) if closed_profits else 0,
            'sum_profit_pct': round(profit_sum, 3) if closed_profits else 0,
            'avg_profit_pct': round(profit_sum / closed_profits, 3) if closed_profits else 0,
        },
    }


def calc_metrics(items: list[dict], day: str | None):
    return _build_day_view(items, day)['metrics']


def get_status():
    raw_pid = None
    keepalive_pid = None
    try:
        if PID_FILE.exists():
            raw_pid = int(PID_FILE.read_text().strip())
    except Exception:
        raw_pid = None
    try:
        if KEEPALIVE_PID_FILE.exists():
            keepalive_pid = int(KEEPALIVE_PID_FILE.read_text().strip())
    except Exception:
        keepalive_pid = None

    hb = read_heartbeat()
    hb_pid = hb.get('pid') if isinstance(hb.get('pid'), int) else None
    running_pid = raw_pid if is_pid_alive(raw_pid) else (hb_pid if is_pid_alive(hb_pid) else None)
    keepalive_running = is_pid_alive(keepalive_pid)
    running = bool(running_pid or keepalive_running)
    pid = running_pid
    stale_pid = raw_pid if raw_pid and not is_pid_alive(raw_pid) else None

    latest_log = None
    log_file = LOGS_DIR / 'monitor.log'
    if log_file.exists():
        latest_log = datetime.fromtimestamp(log_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')

    watchlist_count = None
    hb_watchlist_count = hb.get('watchlist_count') if isinstance(hb, dict) else None
    if isinstance(hb_watchlist_count, int):
        watchlist_count = hb_watchlist_count
    else:
        watchlist = read_json(WATCHLIST_FILE, [])
        watchlist_count = len(watchlist) if isinstance(watchlist, list) else 0

    return {
        'running': running,
        'pid': pid,
        'keepalive_pid': keepalive_pid if keepalive_running else None,
        'heartbeat': hb,
        'stale_pid': stale_pid,
        'watchlist_count': watchlist_count,
        'latest_log_time': latest_log,
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def tail_log(lines=LOG_LINES_LIMIT):
    log_file = LOGS_DIR / 'monitor.log'
    if not log_file.exists():
        return []
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            data = f.readlines()
        return [x.rstrip('\n') for x in data[-max(int(lines), 1):]]
    except Exception:
        return []


def latest_items(items, limit=50):
    if not isinstance(items, list):
        return []
    return list(reversed(items[-limit:]))


def latest_close_from_cache(code: str, day: str | None):
    if not day:
        return None
    fp = MINUTE_CACHE_DIR / f'{code}_{day}.json'
    try:
        data = read_json(fp, [])
        if data:
            return float(data[-1].get('close'))
    except Exception:
        return None
    return None


def build_summary():
    trades = read_json(TRADES_FILE, [])
    signals = read_json(SIGNALS_FILE, [])
    latest_day = latest_trading_day(trades or signals)

    day_view = _build_day_view(trades, latest_day)
    latest_day_trades = day_view['rows']
    latest_day_signals = [x for x in signals if latest_day and str(x.get('time', '')).startswith(latest_day)]
    latest_day_sells = [x for x in latest_day_trades if x.get('type') == 'SELL']
    latest_day_buys = [x for x in latest_day_trades if x.get('type') == 'BUY']
    open_positions = day_view['open_positions']
    latest_metrics = day_view['metrics']

    daily = defaultdict(list)
    for x in trades:
        if x.get('type') != 'SELL':
            continue
        day = str(x.get('time', ''))[:10]
        if day:
            daily[day].append(float(x.get('profit_pct', 0) or 0))
    daily_rows = []
    cumulative = 0.0
    for day in sorted(daily.keys()):
        vals = daily[day]
        day_sum = round(sum(vals), 3)
        cumulative = round(cumulative + day_sum, 3)
        daily_rows.append({
            'day': day,
            'count': len(vals),
            'win_rate': round(sum(1 for v in vals if v > 0) / len(vals) * 100, 2) if vals else 0,
            'sum_profit_pct': day_sum,
            'avg_profit_pct': round(day_sum / len(vals), 3) if vals else 0,
            'cumulative_profit_pct': cumulative,
        })

    sell_reasons = Counter(str(x.get('reason', '')) for x in latest_day_sells)
    buy_reasons = Counter(str(x.get('reason', '')) for x in latest_day_buys)

    recent_signal_cutoff = None
    recent_1h_cutoff = None
    try:
        if latest_day_signals:
            latest_time = max(datetime.strptime(str(x['time']), '%Y-%m-%d %H:%M:%S') for x in latest_day_signals)
            recent_signal_cutoff = latest_time.timestamp() - 300
            recent_1h_cutoff = latest_time.timestamp() - 3600
    except Exception:
        recent_signal_cutoff = None
        recent_1h_cutoff = None

    recent_new_signals = []
    recent_1h_signals = []
    for x in latest_day_signals:
        try:
            ts = datetime.strptime(str(x['time']), '%Y-%m-%d %H:%M:%S').timestamp()
            if recent_signal_cutoff is not None and ts >= recent_signal_cutoff:
                recent_new_signals.append(x)
            if recent_1h_cutoff is not None and ts >= recent_1h_cutoff:
                recent_1h_signals.append(x)
        except Exception:
            pass

    by_code = {}
    for item in latest_day_trades + latest_day_signals:
        code = str(item.get('code', '') or '')
        if not code:
            continue
        row = by_code.setdefault(code, {
            'code': code,
            'name': item.get('name', ''),
            'buy_count': 0,
            'sell_count': 0,
            'latest_time': '',
            'latest_type': '',
            'latest_status': '',
            'latest_profit_pct': None,
            'open': False,
        })
        t = str(item.get('time', '') or '')
        if t > row['latest_time']:
            row['latest_time'] = t
            row['latest_type'] = item.get('type', '')
            row['latest_status'] = item.get('status', '')
            row['latest_profit_pct'] = item.get('profit_pct')
        if item.get('type') == 'BUY':
            row['buy_count'] += 1
        if item.get('type') == 'SELL':
            row['sell_count'] += 1

    open_codes = {str(x.get('code') or '') for x in open_positions}
    for row in by_code.values():
        row['open'] = row['code'] in open_codes

    by_code_rows = sorted(by_code.values(), key=lambda x: (not x['open'], x['latest_time']), reverse=True)

    enhanced_open_positions = []
    for x in latest_items(open_positions, 20):
        row = dict(x)
        try:
            bt = datetime.strptime(str(x.get('time')), '%Y-%m-%d %H:%M:%S')
            row['hold_minutes'] = int((datetime.now() - bt).total_seconds() / 60)
        except Exception:
            row['hold_minutes'] = None
        latest_close = latest_close_from_cache(str(x.get('code')), latest_day)
        row['latest_close'] = latest_close
        try:
            buy_price = float(x.get('price'))
            if latest_close is not None and buy_price > 0:
                row['floating_profit_pct'] = round((latest_close - buy_price) / buy_price * 100, 3)
            else:
                row['floating_profit_pct'] = None
        except Exception:
            row['floating_profit_pct'] = None
        enhanced_open_positions.append(row)

    return {
        'latest_trading_day': latest_day,
        'latest_day_trade_count': latest_metrics['trade_count'],
        'latest_day_closed_count': latest_metrics['closed_count'],
        'latest_day_open_count': latest_metrics['open_count'],
        'latest_day_win_rate': latest_metrics['win_rate'],
        'latest_day_sum_profit_pct': latest_metrics['sum_profit_pct'],
        'latest_day_avg_profit_pct': latest_metrics['avg_profit_pct'],
        'latest_day_signal_count': len(latest_day_signals),
        'daily_rows': list(reversed(daily_rows[-20:])),
        'open_positions': enhanced_open_positions,
        'recent_new_signals': latest_items(recent_new_signals, 20),
        'recent_1h_signals': latest_items(recent_1h_signals, 50),
        'by_code_rows': by_code_rows[:30],
        'latest_day_sell_reason_counts': sell_reasons.most_common(10),
        'latest_day_buy_reason_counts': buy_reasons.most_common(10),
    }


class Handler(BaseHTTPRequestHandler):
    def _safe_write(self, body: bytes):
        with suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            self.wfile.write(body)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self._safe_write(body)

    def _html(self, content, code=200):
        body = content.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ['/', '/index.html']:
            if INDEX_FILE.exists():
                return self._html(INDEX_FILE.read_text(encoding='utf-8'))
            return self._html('<h1>webui missing</h1>', 500)
        if path == '/api/status':
            return self._json(get_status())
        if path == '/api/signals':
            return self._json(latest_items(read_json(SIGNALS_FILE, []), 80))
        if path == '/api/trades':
            return self._json(latest_items(read_json(TRADES_FILE, []), 80))
        if path == '/api/logs':
            return self._json(tail_log())
        if path == '/api/summary':
            return self._json(build_summary())
        return self._json({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        return


if __name__ == '__main__':
    port = int(os.environ.get('FUND_MONITOR_WEBUI_PORT', '8787'))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'Fund monitor web ui: http://0.0.0.0:{port}')
    server.serve_forever()
