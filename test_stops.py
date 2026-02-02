#!/usr/bin/env python3
"""Quick test of different stop configs"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backtest import load_es_data, run_backtest
from bot import DonFuturesConfig

df = load_es_data(5, 0.25)  # 3 months

configs = [
    # (stop, trail_activation, trail_distance)
    (4.0, 1.0, 0.5, "current (tight)"),
    (4.0, 1.0, 1.0, "trail 1.0"),
    (4.0, 1.5, 1.0, "act 1.5, trail 1.0"),
    (4.0, 2.0, 1.0, "act 2.0, trail 1.0"),
    (6.0, 1.0, 1.0, "stop 6, trail 1.0"),
    (6.0, 2.0, 1.5, "stop 6, act 2, trail 1.5"),
    (8.0, 2.0, 2.0, "stop 8, act 2, trail 2"),
]

print(f"{'Config':<25} {'Trades':>7} {'WR%':>7} {'P&L':>10}")
print("-" * 55)

for stop, act, trail, name in configs:
    cfg = DonFuturesConfig(
        stop_pts=stop,
        trail_activation_pts=act,
        trail_distance_pts=trail,
    )
    result = run_backtest(df, cfg, slippage_pts=0)
    print(f"{name:<25} {result['trades']:>7} {result['win_rate']:>6.1f}% ${result['pnl_dollars']:>9,.0f}")
