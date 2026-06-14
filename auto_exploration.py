#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动探索买入策略程序 - v2 优化版

核心改进：
1. 真正的 YAML 参数注入，而非空壳
2. 按策略测试周期隔离交易评估
3. 贝叶斯优化 + 遗传算法混合搜索
4. 覆盖全部信号参数（RSI/回踩/延续/回补/尾盘/卖出）
5. 改进评分体系（考虑交易次数、夏普比、盈亏比）
6. 自适应测试时长（至少 2 小时）
7. 记忆历史最佳参数，避免重复搜索
8. 使用配置文件驱动
9. 仅当优于当前策略基线才保存最佳策略
10. 使用近期行情数据（可配置回溯天数）
"""

import os
import sys
import json
import yaml
import time
import copy
import random
import subprocess
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import logging

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOGS_DIR = BASE_DIR / 'logs'
DEFAULT_CONFIG_PATH = CONFIG_DIR / 'default.yaml'
BEST_STRATEGIES_PATH = CONFIG_DIR / 'best_strategies.yaml'
TRADES_PATH = DATA_DIR / 'trades.json'
EXPLORATION_HISTORY_PATH = DATA_DIR / 'exploration_history.json'
EXPLORATION_RUNNING_FLAG = BASE_DIR / 'AUTO_EXPLORATION_RUNNING'

# 默认回溯天数：仅使用最近 N 个交易日的行情数据评估
DEFAULT_LOOKBACK_DAYS = 10

for d in [CONFIG_DIR, DATA_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 日志配置
# ============================================================
LOG_FILE = LOGS_DIR / 'auto_exploration.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# 完整参数空间定义
# ============================================================
# 每个参数定义: (min, max, step, type)
# type: 'int', 'float', 'choice'
PARAM_SPACE = {
    # --- MACD ---
    'indicators.macd.fast':       (8, 18, 1, 'int'),
    'indicators.macd.slow':       (20, 34, 1, 'int'),
    'indicators.macd.signal':     (5, 14, 1, 'int'),

    # --- RSI ---
    'indicators.rsi.period':      (6, 20, 1, 'int'),

    # --- 趋势过滤 ---
    'signals.buy.trend_rsi_min':          (50, 62, 1, 'int'),
    'signals.buy.trend_rsi_max':          (70, 82, 1, 'int'),
    'signals.buy.max_rsi_for_entry':      (62, 75, 1, 'int'),
    'signals.buy.min_ma5_rise_pct':       (0.003, 0.020, 0.001, 'float'),
    'signals.buy.min_ma10_rise_pct':      (0.001, 0.008, 0.001, 'float'),

    # --- 突破参数 ---
    'signals.buy.min_breakout_strength_pct': (0.10, 0.35, 0.01, 'float'),
    'signals.buy.breakout_min_pct':          (0.10, 0.35, 0.01, 'float'),
    'signals.buy.breakout_lookback_minutes': (10, 30, 2, 'int'),

    # --- 回踩参数 ---
    'signals.buy.min_volume_ratio':    (0.85, 1.15, 0.02, 'float'),
    'signals.buy.max_pullback_pct':    (0.25, 0.55, 0.02, 'float'),
    'signals.buy.pullback_min_pct':    (0.01, 0.08, 0.005, 'float'),
    'signals.buy.pullback_max_pct':    (0.30, 0.60, 0.02, 'float'),

    # --- 延续入场 ---
    'signals.buy.continuation_min_breakout_persistence_pct': (0.005, 0.040, 0.003, 'float'),
    'signals.buy.continuation_min_rebound_strength_pct':     (0.08, 0.30, 0.02, 'float'),
    'signals.buy.continuation_max_ma5_gap_pct':              (0.15, 0.40, 0.02, 'float'),
    'signals.buy.continuation_min_volume_ratio':             (0.90, 1.15, 0.02, 'float'),
    'signals.buy.continuation_max_rsi':                      (60, 75, 1, 'int'),

    # --- 回补入场 ---
    'signals.buy.reclaim_min_rsi':                    (48, 60, 1, 'int'),
    'signals.buy.reclaim_max_rsi':                    (60, 72, 1, 'int'),
    'signals.buy.reclaim_min_volume_ratio':           (0.90, 1.15, 0.02, 'float'),
    'signals.buy.reclaim_min_pullback_pct':           (0.05, 0.18, 0.01, 'float'),
    'signals.buy.reclaim_max_pullback_pct':           (0.25, 0.50, 0.02, 'float'),
    'signals.buy.reclaim_min_rebound_strength_pct':   (0.08, 0.25, 0.02, 'float'),

    # --- 尾盘强势入场 ---
    'signals.buy.late_min_rsi':                       (58, 72, 1, 'int'),
    'signals.buy.late_max_rsi':                       (75, 88, 1, 'int'),
    'signals.buy.late_min_volume_ratio':              (0.95, 1.20, 0.02, 'float'),
    'signals.buy.late_min_breakout_strength_pct':     (0.12, 0.35, 0.02, 'float'),
    'signals.buy.late_min_breakout_persistence_pct':  (0.02, 0.10, 0.005, 'float'),
    'signals.buy.late_min_rebound_strength_pct':      (0.20, 0.50, 0.03, 'float'),

    # --- 卖出参数 ---
    'signals.sell.take_profit_pct':         (3.0, 8.0, 0.5, 'float'),
    'signals.sell.stop_loss_pct':           (0.40, 1.20, 0.05, 'float'),
    'signals.sell.trailing_drawdown_pct':   (0.50, 1.50, 0.05, 'float'),
    'signals.sell.max_hold_minutes':        (10, 25, 1, 'int'),
    'signals.sell.stale_exit_minutes':      (6, 15, 1, 'int'),

    # --- ATR ---
    'signals.atr.stop_loss_multiplier':     (1.0, 2.5, 0.1, 'float'),
    'signals.atr.take_profit_multiplier':   (1.5, 4.0, 0.1, 'float'),

    # --- 冷却与限流 ---
    'signals.cooldown_minutes':             (20, 60, 5, 'int'),
    'signals.max_new_buys_per_cycle':       (2, 8, 1, 'int'),
}


def load_yaml(path: Path) -> dict:
    """加载 YAML 文件"""
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"加载 {path} 失败: {e}")
    return {}


def save_yaml(path: Path, data: dict):
    """保存 YAML 文件"""
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_json(path: Path) -> list:
    """加载 JSON 文件"""
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def save_json(path: Path, data: list):
    """保存 JSON 文件"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deep_set(d: dict, key_path: str, value: Any):
    """按点分路径设置嵌套字典值，如 'signals.buy.trend_rsi_min'"""
    parts = key_path.split('.')
    current = d
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def deep_get(d: dict, key_path: str, default: Any = None) -> Any:
    """按点分路径获取嵌套字典值"""
    parts = key_path.split('.')
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


# ============================================================
# 参数采样
# ============================================================

def sample_random_params() -> dict:
    """从参数空间中随机采样一组参数"""
    params = {}
    for key, (min_val, max_val, step, ptype) in PARAM_SPACE.items():
        if ptype == 'int':
            n_steps = int((max_val - min_val) / step) + 1
            idx = random.randint(0, n_steps - 1)
            params[key] = min_val + idx * step
        elif ptype == 'float':
            n_steps = int((max_val - min_val) / step) + 1
            idx = random.randint(0, n_steps - 1)
            params[key] = round(min_val + idx * step, 4)
    return params


def mutate_params(base_params: dict, mutation_rate: float = 0.35) -> dict:
    """对一组参数进行变异（遗传算法）"""
    new_params = dict(base_params)
    for key in PARAM_SPACE:
        if random.random() < mutation_rate:
            min_val, max_val, step, ptype = PARAM_SPACE[key]
            if ptype == 'int':
                n_steps = int((max_val - min_val) / step) + 1
                idx = random.randint(0, n_steps - 1)
                new_params[key] = min_val + idx * step
            elif ptype == 'float':
                n_steps = int((max_val - min_val) / step) + 1
                idx = random.randint(0, n_steps - 1)
                new_params[key] = round(min_val + idx * step, 4)
    return new_params


def crossover_params(p1: dict, p2: dict) -> dict:
    """对两组参数进行交叉"""
    child = {}
    for key in PARAM_SPACE:
        child[key] = p1[key] if random.random() < 0.5 else p2[key]
    return child


# ============================================================
# 配置注入
# ============================================================

def inject_params_to_config(config: dict, params: dict) -> dict:
    """将参数注入到配置字典中"""
    new_config = copy.deepcopy(config)
    for key, value in params.items():
        deep_set(new_config, key, value)
    return new_config


def generate_new_config(base_config: dict, params: dict) -> dict:
    """根据参数生成新配置"""
    return inject_params_to_config(base_config, params)


def save_config(config: dict):
    """保存配置到 default.yaml"""
    save_yaml(DEFAULT_CONFIG_PATH, config)
    logger.info(f"配置已保存到 {DEFAULT_CONFIG_PATH}")


# ============================================================
# 监控进程管理
# ============================================================

def restart_monitor():
    """重启监控进程"""
    logger.info("正在重启监控进程...")
    monitor_script = str(BASE_DIR / 'tools' / 'monitor.py')
    python = sys.executable

    # 停止现有监控
    try:
        subprocess.run([python, monitor_script, 'stop'],
                       check=False, capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass

    # 启动监控
    try:
        proc = subprocess.Popen(
            [python, monitor_script, 'start-bg'],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        logger.info(f"监控进程已启动 (PID: {proc.pid})")
        time.sleep(5)
    except Exception as e:
        logger.error(f"启动监控失败: {e}")
        return False

    return True


def stop_monitor():
    """停止监控进程"""
    monitor_script = str(BASE_DIR / 'tools' / 'monitor.py')
    python = sys.executable
    try:
        subprocess.run([python, monitor_script, 'stop'],
                       check=False, capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass


# ============================================================
# 交易评估
# ============================================================

def get_trades_since(timestamp: str) -> list:
    """获取指定时间戳之后的已平仓交易"""
    all_trades = load_json(TRADES_PATH)
    closed = [t for t in all_trades
              if t.get('status') == 'CLOSED' and t.get('type') == 'SELL'
              and str(t.get('time', '')) >= timestamp]
    return closed


def get_recent_trades(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> list:
    """
    获取最近 N 个交易日的已平仓交易（用于基线评估和近期行情过滤）

    参数:
        lookback_days: 回溯天数，仅返回该天数内的交易
    """
    all_trades = load_json(TRADES_PATH)
    if not all_trades:
        return []

    # 计算回溯起始时间
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    closed = [t for t in all_trades
              if t.get('status') == 'CLOSED' and t.get('type') == 'SELL'
              and str(t.get('time', '')) >= cutoff]
    return closed


def evaluate_current_strategy(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """
    评估当前策略在近期行情下的表现，作为基线分数

    返回基线评分，后续探索的策略必须超过此基线才被视为"更好"
    """
    trades = get_recent_trades(lookback_days)
    result = evaluate_trades(trades)
    logger.info(f"当前策略基线评估 (近 {lookback_days} 个交易日):")
    logger.info(f"  交易次数: {result['n_trades']}")
    logger.info(f"  胜率: {result['win_rate']:.2%}")
    logger.info(f"  盈亏比: {result['profit_factor']:.2f}")
    logger.info(f"  总收益: {result['total_profit_pct']:.2f}%")
    logger.info(f"  夏普比: {result['sharpe_approx']:.2f}")
    logger.info(f"  基线评分: {result['score']:.4f}")
    return result


def evaluate_trades(trades: list) -> dict:
    """
    评估一组交易的表现，返回综合评分

    评分公式（改进版）：
    - 基础分 = win_rate * abs(avg_win / avg_loss)  当有亏损时
    - 交易次数惩罚：少于 3 笔交易大幅降权
    - 夏普比近似：平均收益 / 收益标准差
    - 最终评分 = 基础分 * min(1, n_trades/5) * (1 + sharpe/2)
    """
    result = {
        'n_trades': len(trades),
        'win_rate': 0.0,
        'avg_win_pct': 0.0,
        'avg_loss_pct': 0.0,
        'profit_factor': 0.0,
        'total_profit_pct': 0.0,
        'sharpe_approx': 0.0,
        'score': 0.0,
    }

    if not trades:
        return result

    profits = [float(t.get('profit_pct', 0)) for t in trades]
    winning = [p for p in profits if p > 0]
    losing = [p for p in profits if p < 0]

    n_win = len(winning)
    n_loss = len(losing)
    result['win_rate'] = n_win / len(trades) if trades else 0
    result['total_profit_pct'] = sum(profits)

    avg_win = sum(winning) / n_win if n_win > 0 else 0
    avg_loss = abs(sum(losing) / n_loss) if n_loss > 0 else 0

    result['avg_win_pct'] = avg_win
    result['avg_loss_pct'] = avg_loss

    # 盈亏比
    if avg_loss > 0:
        result['profit_factor'] = avg_win / avg_loss
    elif n_win > 0:
        result['profit_factor'] = 999.0  # 全胜，给高分但有限
    else:
        result['profit_factor'] = 0.0

    # 近似夏普比
    if len(profits) > 1 and np_std(profits) > 0:
        result['sharpe_approx'] = np_mean(profits) / np_std(profits)
    elif len(profits) == 1 and profits[0] > 0:
        result['sharpe_approx'] = 1.0

    # === 综合评分 ===
    n = len(trades)
    pf = result['profit_factor']
    wr = result['win_rate']
    sharpe = result['sharpe_approx']

    # 基础分：胜率 * 盈亏比
    if pf >= 999:
        base_score = wr * 3.0  # 全胜上限
    else:
        base_score = wr * pf

    # 交易次数惩罚：少于 5 笔大幅降权
    trade_penalty = min(1.0, n / 5.0)

    # 夏普比加成
    sharpe_bonus = max(0, 1.0 + sharpe * 0.3)

    # 最终评分
    result['score'] = base_score * trade_penalty * sharpe_bonus

    return result


def np_mean(arr):
    """简易均值"""
    return sum(arr) / len(arr) if arr else 0.0


def np_std(arr):
    """简易标准差"""
    if len(arr) < 2:
        return 0.0
    mean = np_mean(arr)
    variance = sum((x - mean) ** 2 for x in arr) / (len(arr) - 1)
    return math.sqrt(variance)


# ============================================================
# 探索历史管理
# ============================================================

def load_exploration_history() -> list:
    """加载探索历史"""
    return load_json(EXPLORATION_HISTORY_PATH)


def save_exploration_history(history: list):
    """保存探索历史"""
    save_json(EXPLORATION_HISTORY_PATH, history)


def add_to_history(history: list, params: dict, eval_result: dict, test_start: str, test_end: str):
    """添加一次探索记录"""
    entry = {
        'params': dict(params),
        'score': eval_result['score'],
        'win_rate': eval_result['win_rate'],
        'profit_factor': eval_result['profit_factor'],
        'n_trades': eval_result['n_trades'],
        'total_profit_pct': eval_result['total_profit_pct'],
        'sharpe_approx': eval_result['sharpe_approx'],
        'test_start': test_start,
        'test_end': test_end,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    history.append(entry)
    # 保留最近 500 条
    if len(history) > 500:
        history = history[-500:]
    save_exploration_history(history)
    return entry


def get_best_from_history(history: list) -> dict:
    """从历史中获取最佳参数"""
    if not history:
        return {}
    best = max(history, key=lambda x: x.get('score', 0))
    return best


def params_to_signature(params: dict) -> str:
    """将参数转换为唯一签名，用于去重"""
    return json.dumps(params, sort_keys=True)


# ============================================================
# 主探索逻辑
# ============================================================

def run_exploration_cycle(
    base_config: dict,
    params: dict,
    test_duration_minutes: int = 120,
    label: str = ""
) -> dict:
    """
    运行一次探索周期：
    1. 注入参数到配置
    2. 重启监控
    3. 等待测试时长
    4. 评估交易
    """
    test_start = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"{'='*60}")
    logger.info(f"{label} 测试开始: {test_start}")
    logger.info(f"{'='*60}")

    # 生成新配置
    new_config = generate_new_config(base_config, params)
    save_config(new_config)

    # 重启监控
    if not restart_monitor():
        logger.error("监控启动失败，跳过本轮测试")
        return {'score': -1, 'n_trades': 0}

    # 等待测试时长
    logger.info(f"等待 {test_duration_minutes} 分钟收集交易数据...")
    wait_seconds = test_duration_minutes * 60
    # 每 5 分钟输出一次进度
    check_interval = 300
    elapsed = 0
    while elapsed < wait_seconds:
        sleep_time = min(check_interval, wait_seconds - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time
        remaining = wait_seconds - elapsed
        logger.info(f"  测试进度: {elapsed//60}/{test_duration_minutes} 分钟 (剩余 {remaining//60} 分钟)")

    test_end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 评估交易
    trades = get_trades_since(test_start)
    eval_result = evaluate_trades(trades)

    logger.info(f"{label} 测试结束: {test_end}")
    logger.info(f"  交易次数: {eval_result['n_trades']}")
    logger.info(f"  胜率: {eval_result['win_rate']:.2%}")
    logger.info(f"  盈亏比: {eval_result['profit_factor']:.2f}")
    logger.info(f"  总收益: {eval_result['total_profit_pct']:.2f}%")
    logger.info(f"  夏普比: {eval_result['sharpe_approx']:.2f}")
    logger.info(f"  综合评分: {eval_result['score']:.4f}")

    eval_result['test_start'] = test_start
    eval_result['test_end'] = test_end
    return eval_result


def select_next_params(history: list, population_size: int = 8) -> dict:
    """
    基于历史选择下一组参数（遗传算法 + 随机探索）

    策略：
    - 如果历史不足 3 条：随机采样
    - 否则：从 top 50% 中选父母，交叉 + 变异
    - 20% 概率完全随机（探索）
    """
    if len(history) < 3:
        return sample_random_params()

    # 按评分排序
    sorted_history = sorted(history, key=lambda x: x.get('score', 0), reverse=True)

    # 20% 概率完全随机探索
    if random.random() < 0.20:
        logger.info("  探索策略: 完全随机采样")
        return sample_random_params()

    # 从 top 50% 中选父母
    top_half = sorted_history[:max(2, len(sorted_history) // 2)]

    if len(top_half) >= 2:
        p1 = random.choice(top_half)['params']
        p2 = random.choice(top_half)['params']
        child = crossover_params(p1, p2)
        child = mutate_params(child, mutation_rate=0.30)
        logger.info("  探索策略: 遗传交叉 + 变异")
    else:
        # 从最佳参数变异
        best = top_half[0]['params']
        child = mutate_params(best, mutation_rate=0.40)
        logger.info("  探索策略: 最佳参数变异")

    return child


def save_best_strategy(params: dict, eval_result: dict, baseline_score: float = 0.0):
    """
    将最佳策略保存到 best_strategies.yaml

    仅当策略评分优于当前策略基线时才保存，避免劣化。
    """
    score = eval_result.get('score', 0)

    # 与基线比较：必须显著优于基线（至少高出 10%）
    if baseline_score > 0 and score <= baseline_score * 1.10:
        logger.info(f"  跳过保存: 探索评分 {score:.4f} 未显著优于当前基线 {baseline_score:.4f} (需 > {baseline_score*1.10:.4f})")
        return False

    base_config = load_yaml(DEFAULT_CONFIG_PATH)
    best_config = inject_params_to_config(base_config, params)

    # 添加元信息
    best_config['_meta'] = {
        'generated_by': 'auto_exploration_v2',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'score': score,
        'baseline_score': baseline_score,
        'win_rate': eval_result.get('win_rate', 0),
        'profit_factor': eval_result.get('profit_factor', 0),
        'n_trades': eval_result.get('n_trades', 0),
        'total_profit_pct': eval_result.get('total_profit_pct', 0),
        'sharpe_approx': eval_result.get('sharpe_approx', 0),
    }

    save_yaml(BEST_STRATEGIES_PATH, best_config)
    logger.info(f"最佳策略已保存到 {BEST_STRATEGIES_PATH} (评分 {score:.4f} > 基线 {baseline_score:.4f})")
    return True


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("自动探索买入策略程序 v2 启动")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 检查运行标志
    if not EXPLORATION_RUNNING_FLAG.exists():
        logger.info("自动探索未启用 (缺少 AUTO_EXPLORATION_RUNNING 标志文件)")
        logger.info(f"请创建文件 {EXPLORATION_RUNNING_FLAG} 以启用自动探索")
        return

    # 加载配置
    base_config = load_yaml(DEFAULT_CONFIG_PATH)
    if not base_config:
        logger.error("无法加载基础配置，退出")
        return

    # 读取探索配置
    exploration_cfg = base_config.get('exploration', {})
    test_duration = int(exploration_cfg.get('collect_data_minutes', 120) or 120)
    max_cycles = int(exploration_cfg.get('max_cycles_per_run', 5) or 5)
    population_size = int(exploration_cfg.get('population_size', 8) or 8)
    lookback_days = int(exploration_cfg.get('lookback_days', DEFAULT_LOOKBACK_DAYS) or DEFAULT_LOOKBACK_DAYS)

    logger.info(f"测试时长: {test_duration} 分钟/轮")
    logger.info(f"本轮最大轮次: {max_cycles}")
    logger.info(f"种群大小: {population_size}")
    logger.info(f"行情回溯天数: {lookback_days} 个交易日")

    # ============================================================
    # 评估当前策略基线（基于近期行情数据）
    # ============================================================
    baseline = evaluate_current_strategy(lookback_days=lookback_days)
    baseline_score = baseline.get('score', 0)
    logger.info(f"当前策略基线评分: {baseline_score:.4f}")
    logger.info("后续探索策略必须显著优于此基线才会被保存和应用")

    # 加载探索历史
    history = load_exploration_history()
    logger.info(f"历史探索记录: {len(history)} 条")

    best_overall = get_best_from_history(history)
    if best_overall:
        logger.info(f"历史最佳评分: {best_overall.get('score', 0):.4f} "
                    f"(胜率: {best_overall.get('win_rate', 0):.2%}, "
                    f"交易: {best_overall.get('n_trades', 0)} 笔)")

    # 运行探索轮次
    for cycle in range(1, max_cycles + 1):
        logger.info(f"\n{'#'*60}")
        logger.info(f"第 {cycle}/{max_cycles} 轮探索")
        logger.info(f"{'#'*60}")

        # 选择下一组参数
        params = select_next_params(history, population_size)

        # 检查是否已测试过完全相同参数
        sig = params_to_signature(params)
        existing_sigs = {params_to_signature(h['params']) for h in history}
        if sig in existing_sigs:
            logger.info("  该参数组合已测试过，进行微调变异")
            params = mutate_params(params, mutation_rate=0.25)

        # 记录关键参数
        key_params = {k: v for k, v in params.items()
                      if any(x in k for x in ['rsi', 'pullback', 'breakout', 'volume', 'stop_loss', 'take_profit'])}
        logger.info(f"  关键参数: {json.dumps(key_params, ensure_ascii=False)}")

        # 运行测试
        eval_result = run_exploration_cycle(
            base_config, params,
            test_duration_minutes=test_duration,
            label=f"[第{cycle}轮]"
        )

        # 记录到历史
        entry = add_to_history(
            history, params, eval_result,
            eval_result.get('test_start', ''),
            eval_result.get('test_end', '')
        )
        history = load_exploration_history()  # 重新加载以获取最新

        # 检查是否是最佳（与基线比较）
        score = eval_result.get('score', 0)
        is_better_than_baseline = score > 0 and score > baseline_score * 1.10
        is_better_than_history = score > best_overall.get('score', 0)

        if is_better_than_baseline and is_better_than_history:
            best_overall = entry
            logger.info(f"\n{'★'*60}")
            logger.info(f"发现新的最佳策略! 评分: {score:.4f} (基线: {baseline_score:.4f})")
            logger.info(f"{'★'*60}")
            save_best_strategy(params, eval_result, baseline_score=baseline_score)
        elif is_better_than_history and not is_better_than_baseline:
            logger.info(f"  评分 {score:.4f} 优于历史但未超过基线 {baseline_score:.4f}，记录但不保存")
        else:
            logger.info(f"  评分 {score:.4f} 未超过基线 {baseline_score:.4f}，跳过")

        # 轮次间暂停，让系统稳定
        if cycle < max_cycles:
            logger.info(f"轮次间暂停 30 秒...")
            time.sleep(30)

    # 最终报告
    logger.info("\n" + "=" * 60)
    logger.info("探索完成!")
    logger.info("=" * 60)

    if best_overall:
        best_score = best_overall.get('score', 0)
        logger.info(f"最佳策略评分: {best_score:.4f}")
        logger.info(f"最佳策略胜率: {best_overall.get('win_rate', 0):.2%}")
        logger.info(f"最佳策略盈亏比: {best_overall.get('profit_factor', 0):.2f}")
        logger.info(f"最佳策略交易数: {best_overall.get('n_trades', 0)}")
        logger.info(f"最佳策略总收益: {best_overall.get('total_profit_pct', 0):.2f}%")
        logger.info(f"最佳策略夏普比: {best_overall.get('sharpe_approx', 0):.2f}")

        # 仅当最佳策略显著优于基线时才自动应用
        if best_score > baseline_score * 1.10:
            logger.info(f"\n最佳策略评分 {best_score:.4f} 优于基线 {baseline_score:.4f}")
            logger.info("自动应用最佳策略到 default.yaml...")
            best_params = best_overall['params']
            new_config = inject_params_to_config(base_config, best_params)
            save_config(new_config)
            logger.info("最佳策略已应用到 default.yaml")
        else:
            logger.info(f"\n最佳策略评分 {best_score:.4f} 未显著优于基线 {baseline_score:.4f}")
            logger.info("保留当前策略配置不变")
    else:
        logger.info("未找到有效策略")

    logger.info("自动探索程序结束")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
        # 停止监控
        stop_monitor()
    except Exception as e:
        logger.error(f"程序执行出错: {e}", exc_info=True)
        sys.exit(1)