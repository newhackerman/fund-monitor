#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知推送模块
"""

import requests
import json
import sys
import time as _time
from datetime import datetime


# ============================================================
# 底层发送（检查 errcode）
# ============================================================

def send_dingtalk(webhook: str, title: str, text: str) -> bool:
    """发送钉钉通知（纯文本）。检查 errcode，返回真实成功/失败。"""
    try:
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        data = {
            "msgtype": "text",
            "text": {
                "content": f"{title}\n{text}"
            }
        }
        response = requests.post(webhook, headers=headers, data=json.dumps(data), timeout=10)
        if response.status_code != 200:
            print(f"钉钉通知HTTP错误: {response.status_code}", file=sys.stderr)
            return False
        result = response.json()
        errcode = result.get('errcode', -1)
        if errcode != 0:
            print(f"钉钉通知业务错误: errcode={errcode}, errmsg={result.get('errmsg', '')}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"钉钉通知发送失败：{e}", file=sys.stderr)
        return False

def send_wechat(key: str, title: str, content: str) -> bool:
    """发送企业微信通知（纯文本）。检查 errcode，返回真实成功/失败。"""
    try:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
        data = {
            "msgtype": "text",
            "text": {
                "content": f"{title}\n{content}"
            }
        }
        response = requests.post(url, json=data, timeout=10)
        if response.status_code != 200:
            print(f"企业微信通知HTTP错误: {response.status_code}", file=sys.stderr)
            return False
        result = response.json()
        errcode = result.get('errcode', -1)
        if errcode != 0:
            print(f"企业微信通知业务错误: errcode={errcode}, errmsg={result.get('errmsg', '')}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"企业微信通知发送失败：{e}", file=sys.stderr)
        return False


# ============================================================
# 重试机制
# ============================================================

# 重试间隔（秒），共9次重试 + 首次 = 10次尝试
_RETRY_INTERVALS = [2, 4, 8, 16, 30, 30, 30, 30, 30]
# 10次全失败后的休息时间（秒）
_RETRY_LONG_WAIT = 1800  # 30分钟

def send_with_retry(send_fn, *args, **kwargs) -> bool:
    """带重试的发送：失败重试最多10次，10次仍失败休息30分钟后再试一次。

    成功后不重试，立即返回 True。
    """
    for attempt in range(1, 11):
        if send_fn(*args, **kwargs):
            if attempt > 1:
                print(f"第{attempt}次尝试成功", file=sys.stderr)
            return True
        if attempt < 10:
            delay = _RETRY_INTERVALS[attempt - 1]
            print(f"发送失败，{delay}秒后重试（第{attempt + 1}/10次）", file=sys.stderr)
            _time.sleep(delay)

    # 10次全失败，休息30分钟后再试一次
    print(f"10次重试均失败，休息30分钟后最后尝试一次", file=sys.stderr)
    _time.sleep(_RETRY_LONG_WAIT)
    if send_fn(*args, **kwargs):
        print("30分钟后重试成功", file=sys.stderr)
        return True
    print("全部重试失败，放弃", file=sys.stderr)
    return False


def send_terminal(signal: dict, sound: bool = True):
    """终端通知"""
    from signals import format_signal

    print("\n" + "=" * 60)
    print(format_signal(signal))
    print("=" * 60)

    if sound:
        # 播放提示音
        try:
            print('\a', end='')  # 终端蜂鸣
        except:
            pass

def notify(signal: dict, config: dict):
    """发送通知"""
    notify_cfg = config.get('notify', {})

    title = f"{'买入' if signal['type'] == 'BUY' else '卖出'}信号 - {signal['code']}"
    text = f"""
代码: {signal['code']} ({signal['name']})
价格: {signal['price']:.3f}
原因: {signal['reason']}
时间: {signal['time']}
置信度: {signal['confidence']}
"""

    # 钉钉
    if notify_cfg.get('dingtalk', {}).get('enabled'):
        webhook = notify_cfg['dingtalk'].get('webhook', '')
        if webhook:
            send_with_retry(send_dingtalk, webhook, title, text)

    # 企业微信
    if notify_cfg.get('wechat', {}).get('enabled'):
        key = notify_cfg['wechat'].get('key', '')
        if key:
            send_with_retry(send_wechat, key, title, text)

    # 终端
    if notify_cfg.get('terminal', {}).get('enabled', True):
        send_terminal(signal, notify_cfg.get('terminal', {}).get('sound', True))

if __name__ == '__main__':
    print("通知模块测试")
