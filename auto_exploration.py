#!/usr/bin/env python3
"""
自动探索买入策略程序
"""

import os
import sys
import time
import json
import subprocess
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/node/.openclaw/workspace/skills/fund-monitor/logs/auto_exploration.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 策略参数范围定义
PARAM_RANGES = {
    'macd_fast': range(10, 20),
    'macd_slow': range(20, 35),
    'macd_signal': range(5, 15),
    'volume_multiplier': [1.2, 1.5, 1.8, 2.0, 2.5],
    'rsi_period': range(5, 20),
    'rsi_overbought': range(65, 85),
    'rsi_oversold': range(20, 40)
}

def load_current_config():
    """加载当前监控配置"""
    config_path = '/home/node/.openclaw/workspace/skills/fund-monitor/config/default.yaml'
    try:
        with open(config_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("配置文件不存在，使用默认配置")
        return ""

def save_config(config_content):
    """保存配置"""
    config_path = '/home/node/.openclaw/workspace/skills/fund-monitor/config/default.yaml'
    with open(config_path, 'w') as f:
        f.write(config_content)

def restart_monitor():
    """重启监控进程"""
    logger.info("正在重启监控进程...")
    
    # 停止现有监控
    try:
        subprocess.run([
            'python3', 
            '/home/node/.openclaw/workspace/skills/fund-monitor/tools/monitor.py', 
            'stop'
        ], check=True, capture_output=True)
        time.sleep(2)
    except subprocess.CalledProcessError:
        pass  # 可能已经停止
    
    # 启动监控
    subprocess.Popen([
        'nohup',
        'python3',
        '/home/node/.openclaw/workspace/skills/fund-monitor/tools/monitor.py',
        'start'
    ], stdout=open('/home/node/.openclaw/workspace/skills/fund-monitor/logs/monitor_nohup.log', 'w'),
       stderr=subprocess.STDOUT,
       start_new_session=True)
    
    time.sleep(5)
    logger.info("监控进程重启完成")

def evaluate_strategy():
    """评估当前策略表现"""
    # 这里应该从交易记录中计算策略表现
    # 简化实现：返回模拟评分
    try:
        with open('/home/node/.openclaw/workspace/skills/fund-monitor/data/trades.json', 'r') as f:
            trades = json.load(f)
        
        # 计算胜率和盈亏比
        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        total_trades = len(trades)
        
        if total_trades == 0:
            return 0, 0
        
        win_rate = len(winning_trades) / total_trades
        avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t['pnl'] for t in trades if t.get('pnl', 0) < 0) / (total_trades - len(winning_trades)) if total_trades > len(winning_trades) else 0
        
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        
        score = win_rate * profit_factor
        return score, win_rate
    except Exception as e:
        logger.error(f"评估策略时出错: {e}")
        return 0, 0

def generate_new_config(base_config, params):
    """根据参数生成新配置"""
    # 这里应该实际修改配置文件
    # 简化实现：只记录参数变化
    logger.info(f"生成新配置参数: {params}")
    return base_config

def main():
    """主函数"""
    logger.info("开始自动探索买入策略程序")
    
    # 检查是否应该运行
    if not os.path.exists('/home/node/.openclaw/workspace/skills/fund-monitor/AUTO_EXPLORATION_RUNNING'):
        logger.info("自动探索未启用，退出")
        return
    
    # 加载基础配置
    base_config = load_current_config()
    
    best_score = 0
    best_params = {}
    
    # 简化的参数搜索 - 实际应用中应该使用更智能的搜索算法
    param_combinations = [
        {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'volume_multiplier': 1.5},
        {'macd_fast': 10, 'macd_slow': 22, 'macd_signal': 7, 'volume_multiplier': 1.8},
        {'macd_fast': 14, 'macd_slow': 30, 'macd_signal': 10, 'volume_multiplier': 2.0}
    ]
    
    for i, params in enumerate(param_combinations):
        logger.info(f"测试第 {i+1}/{len(param_combinations)} 组参数: {params}")
        
        # 生成并应用新配置
        new_config = generate_new_config(base_config, params)
        save_config(new_config)
        
        # 重启监控以应用新配置
        restart_monitor()
        
        # 等待一段时间收集数据 (简化实现)
        logger.info("等待10分钟收集数据...")
        time.sleep(600)  # 实际应用中应该是更长时间
        
        # 评估策略表现
        score, win_rate = evaluate_strategy()
        logger.info(f"参数组合 {params} 得分: {score:.4f}, 胜率: {win_rate:.2%}")
        
        # 更新最佳参数
        if score > best_score:
            best_score = score
            best_params = params
            logger.info(f"发现更好策略! 得分: {score:.4f}")
    
    logger.info(f"最佳参数组合: {best_params}, 得分: {best_score:.4f}")
    logger.info("自动探索买入策略程序完成")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序执行出错: {e}")
        sys.exit(1)