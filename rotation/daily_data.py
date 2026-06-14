#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线数据获取与缓存（腾讯主源 + 新浪兜底）

数据源选择（实测于 2026-06）：
- 腾讯 web.ifzq.gtimg.cn：约 640 bars/标的（约 2.5 年），前复权 -> 主源（项目实时数据也用腾讯）
- 新浪 quotes.sina.cn：1500 bars/标的（约 6 年），稳定，前复权 -> 兜底（数据更长）
- 东财 push2his：服务器端点在沙箱不可达 -> 不用

字段：date, open, close, high, low, volume（前复权）
本地 parquet 缓存按 code 命名，回测零网络。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / 'data' / 'daily_cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT = 15
RETRIES = 3
RETRY_DELAY = 0.6
INTER_REQUEST_DELAY = 0.15

SINA_KLINE = ('https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService'
              '.getKLineData')
TX_KLINE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    # 沙箱系统代理会间歇拦截，禁用 trust_env 走直连
    s.trust_env = False
    return s


_SESSION = _make_session()


def _code_with_prefix(code: str) -> str:
    """6位代码 -> sh/sz 带前缀。5/6/9/11 开头为沪，其余（1/3/0/15）为深。"""
    code = str(code).strip()
    market = 'sh' if code[0] in ('5', '6', '9') else 'sz'
    return f'{market}{code}'


# ---------------- 新浪 ----------------

def _sina_parse(text: str) -> list[dict]:
    """解析新浪 jsonp 返回：var=([...])"""
    start = text.find('=(')
    if start < 0:
        return []
    payload = text[start + 2: text.rfind(')')]
    if not payload:
        return []
    return json.loads(payload)


def fetch_sina_daily(code: str, datalen: int = 1500) -> pd.DataFrame:
    """新浪日线（前复权）。datalen 控制返回根数，最多约 1500。"""
    sym = _code_with_prefix(code)
    params = {'symbol': sym, 'scale': 240, 'ma': 'no', 'datalen': datalen}
    last_exc = None
    for _ in range(RETRIES):
        try:
            r = _SESSION.get(SINA_KLINE, params=params, timeout=TIMEOUT)
            rows = _sina_parse(r.text)
            if rows:
                df = pd.DataFrame(rows)
                # 新浪返回字段：day,open,high,low,close,volume
                df = df.rename(columns={'day': 'date'})
                for c in ['open', 'high', 'low', 'close', 'volume']:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                df['date'] = pd.to_datetime(df['date'])
                return df[['date', 'open', 'close', 'high', 'low', 'volume']].dropna(
                    subset=['close']).reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(RETRY_DELAY)
    logger.debug(f'sina {code} 失败: {last_exc}')
    return pd.DataFrame()


# ---------------- 腾讯（兜底） ----------------

def fetch_tencent_daily(code: str, datalen: int = 640) -> pd.DataFrame:
    """腾讯日线前复权。datalen 最大约 640。返回格式：qfqday=[[date,open,close,high,low,vol],...]"""
    sym = _code_with_prefix(code)
    params_str = f'param={sym},day,,,{datalen},qfq'
    url = f'{TX_KLINE}?{params_str}'
    last_exc = None
    for _ in range(RETRIES):
        try:
            r = _SESSION.get(url, timeout=TIMEOUT)
            j = r.json()
            d = (j.get('data') or {}).get(sym, {})
            rows = d.get('qfqday') or d.get('day') or []
            if rows:
                df = pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
                for c in ['open', 'close', 'high', 'low', 'volume']:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                df['date'] = pd.to_datetime(df['date'])
                return df[['date', 'open', 'close', 'high', 'low', 'volume']].dropna(
                    subset=['close']).reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(RETRY_DELAY)
    logger.debug(f'tencent {code} 失败: {last_exc}')
    return pd.DataFrame()


# ---------------- 统一入口 + 缓存 ----------------

def fetch_etf_daily(code: str, datalen: int = 640) -> pd.DataFrame:
    """主源腾讯，失败兜底新浪（新浪可拿更长历史）。"""
    df = fetch_tencent_daily(code, datalen=min(datalen, 640))
    if not df.empty:
        return df
    logger.info(f'{code} 腾讯失败，尝试新浪兜底')
    return fetch_sina_daily(code, datalen=max(datalen, 1500))


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f'{code}.parquet'


def load_daily(code: str, use_cache: bool = True, refresh: bool = False,
               datalen: int = 640) -> pd.DataFrame:
    """加载单只 ETF 日线，带本地缓存。

    缓存以 code 命名（不绑日期范围），方便增量更新。
    refresh=True 时强制重新拉取并覆盖缓存。
    """
    path = _cache_path(code)
    if use_cache and not refresh and path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    df = fetch_etf_daily(code, datalen=datalen)
    if not df.empty:
        try:
            df.to_parquet(path, index=False)
        except Exception as e:  # noqa: BLE001
            logger.debug(f'{code} 缓存写入失败: {e}')
    return df


def load_pool(codes: list[str], use_cache: bool = True, refresh: bool = False,
              min_bars: int = 60, datalen: int = 640) -> dict[str, pd.DataFrame]:
    """批量加载 ETF 池日线。返回 {code: df}，跳过失败/数据不足的标的。"""
    result: dict[str, pd.DataFrame] = {}
    n_fail = 0
    for i, code in enumerate(codes):
        df = load_daily(code, use_cache=use_cache, refresh=refresh, datalen=datalen)
        if df.empty or len(df) < min_bars:
            logger.info(f'{code} 数据不足（{len(df)} < {min_bars}），跳过')
            n_fail += 1
        else:
            result[code] = df
        if (i + 1) % 10 == 0:
            logger.info(f'  已加载 {i+1}/{len(codes)} ...')
        time.sleep(INTER_REQUEST_DELAY)
    logger.info(f'加载完成：成功 {len(result)}/{len(codes)}，跳过 {n_fail}')
    return result


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    pool = ['518880', '513100', '159915', '511880', '510300']
    data = load_pool(pool)
    for c, df in data.items():
        print(f'{c}: {len(df)} bars {df["date"].iloc[0].date()}~{df["date"].iloc[-1].date()}')
