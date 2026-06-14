#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""七星高照 ETF 轮动策略 —— 回测入口

用法：
    python -m rotation.run                      # 用 config/rotation.yaml 默认
    python -m rotation.run --refresh            # 强制重新拉数据
    python -m rotation.run --start 2025-01-01   # 自定义回测起点

输出：
    - 终端打印核心指标表
    - data/rotation_backtest_report.json   完整报告
    - data/rotation_equity_curve.csv       净值曲线
    - data/rotation_trades.csv             交易明细
    - rotation/REPORT.md                   人类可读报告
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

from . import daily_data
from .backtest import run_backtest

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'rotation.yaml'
DATA_DIR = BASE_DIR / 'data'

logger = logging.getLogger('rotation')


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description='七星高照 ETF 轮动回测')
    parser.add_argument('--refresh', action='store_true', help='强制重新拉取日线数据')
    parser.add_argument('--start', default=None, help='回测起点 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='回测终点 YYYY-MM-DD')
    parser.add_argument('--no-cache', action='store_true', help='不使用本地缓存')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    cfg = load_config()
    etf_pool = cfg['etf_pool']
    defensive = cfg['defensive_etf']
    benchmark = cfg['benchmark']
    params = cfg['params']
    bt_cfg = dict(cfg['backtest'])
    if args.start:
        bt_cfg['start'] = args.start
    if args.end:
        bt_cfg['end'] = args.end

    all_codes = list(set(etf_pool + [defensive, benchmark]))

    # ---------- 1. 拉数据 ----------
    logger.info(f'加载日线数据：{len(all_codes)} 个标的（refresh={args.refresh}）')
    data = daily_data.load_pool(
        all_codes, use_cache=not args.no_cache, refresh=args.refresh, min_bars=80)
    ok_codes = set(data.keys())
    logger.info(f'数据就绪：{len(ok_codes)}/{len(all_codes)} 标的可用')

    bench_daily = data.get(benchmark)
    if bench_daily is None or bench_daily.empty:
        logger.error(f'基准 {benchmark} 无数据，无法回测')
        sys.exit(1)

    usable_pool = [c for c in etf_pool if c in ok_codes]
    if defensive not in ok_codes:
        logger.warning(f'防御 ETF {defensive} 无数据，回测期间空仓将不转防御')
    logger.info(f'有效候选池：{len(usable_pool)} 只，防御={defensive}({"有" if defensive in ok_codes else "无"})')

    # ---------- 2. 回测 ----------
    logger.info(f'开始回测：{bt_cfg["start"]} ~ {bt_cfg["end"]}，初始资金 {bt_cfg["initial_capital"]}')
    result = run_backtest(data, bench_daily, usable_pool, defensive, params, bt_cfg)

    # ---------- 2b. 基准对照（等权池 + 单标的上界 + 样本外分段）----------
    baselines = _compute_baselines(data, usable_pool, bench_daily,
                                   bt_cfg['start'], bt_cfg['end'])
    splits = _compute_split_validation(data, bench_daily, usable_pool,
                                       defensive, params, bt_cfg)

    # ---------- 3. 输出 ----------
    metrics = result.metrics
    print('\n' + '=' * 60)
    print('七星高照 ETF 轮动 —— 回测结果')
    print('=' * 60)
    print(f"回测区间:    {metrics['start_date']} ~ {metrics['end_date']} ({metrics['n_trade_days']} 交易日)")
    print(f"初始资金:    {metrics['initial_capital']:,.0f}")
    print(f"期末净值:    {metrics['final_equity']:,.2f}")
    print(f"累计收益:    {metrics['total_return_pct']:+.2f}%")
    print(f"年化收益:    {metrics['annual_return_pct']:+.2f}%")
    print(f"最大回撤:    {metrics['max_drawdown_pct']:.2f}%")
    print(f"夏普比率:    {metrics['sharpe']:.3f}")
    print(f"Calmar:      {metrics['calmar']:.3f}")
    print(f"基准收益:    {metrics['benchmark_return_pct']:+.2f}%" if metrics.get('benchmark_return_pct') is not None else "基准收益:    N/A")
    print(f"超额收益:    {metrics['excess_return_pct']:+.2f}%" if metrics.get('excess_return_pct') is not None else "超额收益:    N/A")
    print('-' * 60)
    print(f"买入笔数:    {metrics['n_buys']}")
    print(f"卖出笔数:    {metrics['n_sells']}")
    print(f"胜率:        {metrics['win_rate_pct']:.1f}%")
    print(f"平均盈利:    {metrics['avg_win_pct']:+.2f}%")
    print(f"平均亏损:    {metrics['avg_loss_pct']:+.2f}%")
    print(f"盈亏比:      {metrics['profit_factor']}")
    print(f"日均换手:    {metrics['turnover_per_day']}")
    print('=' * 60)

    # 落盘
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        'strategy': cfg['strategy'],
        'backtest_config': bt_cfg,
        'params': params,
        'metrics': metrics,
        'baselines': baselines,
        'splits': splits,
        'n_pool_used': len(usable_pool),
        'pool_missing': sorted(set(etf_pool) - ok_codes),
        'range_bound_switches': result.range_bound_log,
    }
    with open(DATA_DIR / 'rotation_backtest_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    result.equity_curve.to_csv(DATA_DIR / 'rotation_equity_curve.csv', index=False)
    pd.DataFrame(result.trades).to_csv(DATA_DIR / 'rotation_trades.csv', index=False)
    logger.info(f'报告已落盘：data/rotation_backtest_report.json / rotation_equity_curve.csv / rotation_trades.csv')

    # 写人类可读报告
    _write_markdown_report(report, result)
    logger.info('人类可读报告：rotation/REPORT.md')


def _compute_baselines(data: dict, pool: list[str], bench_daily,
                       start: str, end: str) -> dict:
    """计算对照基准：等权全池买入持有 + 池内事后最强单标的 + 沪深300。

    用途：判读策略超额收益来自"选股alpha"还是"池子beta"。
    """
    import numpy as np
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    def _period_ret(df):
        d = df.set_index('date')['close']
        d = d.loc[(d.index >= start_ts) & (d.index <= end_ts)]
        if len(d) < 2:
            return float('nan')
        return d.iloc[-1] / d.iloc[0] - 1

    # 等权全池（按日收益率均值）
    rets = {}
    for c in pool:
        if c not in data:
            continue
        df = data[c].set_index('date').loc[start_ts:end_ts]
        if len(df) < 2:
            continue
        rets[c] = df['close'].pct_change()
    if rets:
        eq_ret = pd.DataFrame(rets).mean(axis=1).fillna(0.0)
        eq_equity = (1 + eq_ret).cumprod()
        eq_total = float(eq_equity.iloc[-1] - 1)
        n_days = (eq_ret.index[-1] - eq_ret.index[0]).days
        eq_annual = (eq_equity.iloc[-1]) ** (365.0 / max(n_days, 1)) - 1
    else:
        eq_total = eq_annual = float('nan')

    # 池内事后单标的收益
    single = {c: _period_ret(data[c]) for c in pool if c in data}
    single = {c: r for c, r in single.items() if not np.isnan(r)}
    top3 = sorted(single.items(), key=lambda x: x[1], reverse=True)[:3]

    bench_ret = _period_ret(bench_daily) if bench_daily is not None else float('nan')

    return {
        'equal_weight_pool_total_pct': round(eq_total * 100, 2),
        'equal_weight_pool_annual_pct': round(eq_annual * 100, 2),
        'pool_mean_total_pct': round(float(np.mean(list(single.values()))) * 100, 2)
            if single else None,
        'pool_median_total_pct': round(float(np.median(list(single.values()))) * 100, 2)
            if single else None,
        'top3_codes': [(c, round(r * 100, 2)) for c, r in top3],
        'benchmark_total_pct': round(bench_ret * 100, 2)
            if not np.isnan(bench_ret) else None,
        'pool_size': len(single),
    }


def _compute_split_validation(data, bench_daily, pool, defensive, params, bt_cfg) -> dict:
    """样本内外分段验证：把回测区间对半切，分别跑，看是否一致。

    判读：
    - 两段都显著正 -> 非过拟合
    - 样本内正、样本外负/近0 -> 过拟合
    - 两段都正但样本外大幅衰减 -> 部分有效，谨慎
    """
    from .backtest import run_backtest as _run
    start = pd.Timestamp(bt_cfg['start'])
    end = pd.Timestamp(bt_cfg['end'])
    mid = start + (end - start) / 2

    result = {}
    for label, s, e in [('in_sample', start, mid), ('out_of_sample', mid, end)]:
        cfg2 = dict(bt_cfg)
        cfg2['start'] = s.strftime('%Y-%m-%d')
        cfg2['end'] = e.strftime('%Y-%m-%d')
        try:
            r = _run(data, bench_daily, pool, defensive, params, cfg2)
            m = r.metrics
            result[label] = {
                'start': m['start_date'], 'end': m['end_date'],
                'n_days': m['n_trade_days'],
                'total_return_pct': m['total_return_pct'],
                'annual_return_pct': m['annual_return_pct'],
                'max_drawdown_pct': m['max_drawdown_pct'],
                'sharpe': m['sharpe'],
                'win_rate_pct': m['win_rate_pct'],
            }
        except Exception as e:  # noqa: BLE001
            result[label] = {'error': str(e)}
    return result


def _split_verdict(sp: dict) -> str:
    """根据样本内外分段实际结果，生成诚实的判读结论。"""
    ins = sp.get('in_sample', {})
    outs = sp.get('out_of_sample', {})
    if 'error' in ins or 'error' in outs:
        return '**判读**：分段验证出错，无法下结论。'
    r_in = ins.get('total_return_pct', 0)
    r_out = outs.get('total_return_pct', 0)

    if r_in > 5 and r_out > 5:
        return (f'**判读**：样本内 {r_in:+.1f}%、样本外 {r_out:+.1f}%，两段都显著正收益 → '
                f'**未发现过拟合**，策略在该候选池上稳健有效。')
    if r_in > 5 and r_out <= 5:
        return (f'**判读**：样本内 {r_in:+.1f}%、样本外 {r_out:+.1f}%，样本外明显衰减 → '
                f'**疑似过拟合或策略失效**，实盘需高度警惕。')
    if r_in <= 5 and r_out > 5:
        return (f'**判读**：样本内 {r_in:+.1f}%、样本外 {r_out:+.1f}%，前弱后强 → '
                f'**策略表现高度依赖行情**，收益主要来自特定时段的趋势行情，'
                f'不具备跨期稳定性，不应视为稳健 alpha。')
    return (f'**判读**：样本内 {r_in:+.1f}%、样本外 {r_out:+.1f}%，两段都弱 → '
            f'**策略在该候选池上无效**，不建议实盘。')


def _write_markdown_report(report: dict, result) -> None:
    m = report['metrics']
    lines = [
        '# 七星高照 ETF 轮动策略 —— 回测报告',
        '',
        f'**策略来源**：{report["strategy"]["source"]}',
        f'**回测区间**：{m["start_date"]} ~ {m["end_date"]}（{m["n_trade_days"]} 交易日）',
        f'**生成时间**：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}',
        '',
        '## 核心指标',
        '',
        '| 指标 | 值 |',
        '|---|---|',
        f'| 初始资金 | {m["initial_capital"]:,.0f} |',
        f'| 期末净值 | {m["final_equity"]:,.2f} |',
        f'| 累计收益 | {m["total_return_pct"]:+.2f}% |',
        f'| 年化收益 | {m["annual_return_pct"]:+.2f}% |',
        f'| 最大回撤 | {m["max_drawdown_pct"]:.2f}% |',
        f'| 夏普比率 | {m["sharpe"]:.3f} |',
        f'| Calmar | {m["calmar"]:.3f} |',
        f'| 基准收益 | {m["benchmark_return_pct"]:+.2f}% |' if m.get('benchmark_return_pct') is not None else '| 基准收益 | N/A |',
        f'| 超额收益 | {m["excess_return_pct"]:+.2f}% |' if m.get('excess_return_pct') is not None else '| 超额收益 | N/A |',
        '',
        '## 交易统计',
        '',
        '| 指标 | 值 |',
        '|---|---|',
        f'| 买入笔数 | {m["n_buys"]} |',
        f'| 卖出笔数 | {m["n_sells"]} |',
        f'| 胜率 | {m["win_rate_pct"]:.1f}% |',
        f'| 平均盈利 | {m["avg_win_pct"]:+.2f}% |',
        f'| 平均亏损 | {m["avg_loss_pct"]:+.2f}% |',
        f'| 盈亏比 | {m["profit_factor"]} |',
        f'| 日均换手 | {m["turnover_per_day"]} |',
        '',
        '## 基准对照（判读 alpha 来源）',
        '',
        '> 关键问题：超额收益来自"选股"还是"候选池本身在涨"？',
        '> 若策略 ≈ 等权全池，说明收益是池 beta；若显著高于等权池，才是选股 alpha。',
        '',
    ]
    b = report.get('baselines') or {}
    if b:
        lines += [
            '| 对照基准 | 累计收益 | 说明 |',
            '|---|---|---|',
            f'| **策略（轮动选股）** | **{m["total_return_pct"]:+.2f}%** | 本策略 |',
            f'| 等权全池买入持有 | {b.get("equal_weight_pool_total_pct","N/A"):+}% | '
            f'把候选池所有标的等权买入不动，衡量池子 beta |',
            f'| 池内事后均值 | {b.get("pool_mean_total_pct","N/A"):+}% | '
            f'池内所有标的收益均值（事后才知道） |',
            f'| 池内事事后中位 | {b.get("pool_median_total_pct","N/A"):+}% | 池内收益中位数 |',
            f'| 沪深300 | {b.get("benchmark_total_pct","N/A"):+}% | 市场 beta |',
        ]
        if b.get('top3_codes'):
            top3 = '、'.join([f'{c}({r:+.0f}%)' for c, r in b['top3_codes']])
            lines.append(f'| 池内事后 TOP3 | {top3} | 单标的收益上界（作弊基准） |')
        alpha_vs_eq = (m['total_return_pct'] - (b.get('equal_weight_pool_total_pct') or 0))
        lines += [
            '',
            f'**策略相对等权池超额：{alpha_vs_eq:+.1f}%**（>0 表示选股确实贡献了附加价值）',
            '',
        ]

    # 样本外验证
    sp = report.get('splits') or {}
    if sp:
        lines += ['## 样本内外分段验证（同一套参数，不重新拟合）', '']
        lines += ['| 段 | 区间 | 交易日 | 累计 | 年化 | 回撤 | 夏普 | 胜率 |',
                  '|---|---|---|---|---|---|---|---|']
        for label, name in [('in_sample', '样本内（前半）'), ('out_of_sample', '样本外（后半）')]:
            d = sp.get(label, {})
            if 'error' in d:
                lines.append(f'| {name} | 失败 | - | - | - | - | - | - |')
            else:
                lines.append(
                    f'| {name} | {d["start"]}~{d["end"]} | {d["n_days"]} | '
                    f'{d["total_return_pct"]:+.1f}% | {d["annual_return_pct"]:+.1f}% | '
                    f'{d["max_drawdown_pct"]:.1f}% | {d["sharpe"]:.2f} | '
                    f'{d["win_rate_pct"]:.0f}% |')
        lines += ['', _split_verdict(sp), '']

    lines += [
        '## ⚠️ 风险提示与已知局限',
        '',
        '1. **候选池单一资产类**：本候选池全部为跨境权益 ETF（纳指/恒生/中概/日经等），'
        '彼此高度正相关，缺乏黄金/债券等低相关资产做对冲。聚宽原池含黄金(518880)、'
        '债券(511220)、豆粕(159985)等多类资产，那是原策略高收益的关键。**同逻辑换到纯跨境权益池，效果大幅下降。**',
        '2. **行情依赖性强**：样本内外分段显示策略前弱后强，收益主要来自特定时段的趋势行情，'
        '**不具备跨期稳定性**，不应视为稳健 alpha。',
        '3. **理想化执行**：回测用当日收盘价成交，实盘 13:10 挂单未必按收盘价成交，'
        '存在滑点（已计入万一双边滑点，但极端波动时实际更大）。',
        '4. **流动性风险**：满仓单只 ETF，部分小盘跨境 ETF 日均成交额低，'
        '实盘大资金冲击成本高，回测未充分反映。',
        '5. **溢价风险（QDII 跨境 ETF）**：跨境标的常现高溢价（尤其 513050/159509 等），'
        '本回测已关闭溢价过滤（本地无净值数据源），实盘需手动规避高溢价标的。',
        '6. **无防御标的**：池内无货币/债券类 ETF，策略在"无目标"时直接空仓，'
        '不会像聚宽原策略那样切换到防御资产。',
        '7. **不构成投资建议**：本报告仅为策略逻辑移植与回测验证，实盘交易自负盈亏。',
        '',
        '## 数据说明',
        '',
        f'- 有效候选池：{report["n_pool_used"]} 只 ETF',
        f'- 缺失标的（数据不足/拉取失败）：{", ".join(report["pool_missing"]) or "无"}',
        f'- 数据源：腾讯日线（主）+ 新浪（兜底），前复权',
        '',
        '## 与聚宽原策略的差异（移植简化）',
        '',
        '1. **执行价**：聚宽 13:10 用实时价，本回测用当日收盘价（日频轮动差异通常 <0.2%）',
        '2. **溢价率过滤**：本地无基金净值数据源，已关闭（`enable_premium_filter: false`）',
        '3. **交易成本**：万一佣金 + 最低 5 元 + 万一滑点，与聚宽 OrderCost 一致',
        '4. **交易规则**：候选池全部为 T+0 跨境 ETF，当日买入当日可卖出（`t_plus_zero: true`）',
        '5. **涨跌停**：用收盘价近似判断（ETF 10% 涨跌停）',
        '',
        '## 震荡期切换记录',
        '',
    ]
    if report['range_bound_switches']:
        lines.append('| 日期 | 切换 |')
        lines.append('|---|---|')
        for sw in report['range_bound_switches']:
            lines.append(f'| {pd.Timestamp(sw["date"]).date()} | {sw["from"]} → {sw["to"]} |')
    else:
        lines.append('（回测期间未触发震荡期切换）')
    lines.append('')

    Path(BASE_DIR / 'rotation' / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
