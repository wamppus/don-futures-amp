#!/usr/bin/env python3
"""
Parameter Sweep v2 - $1.24 commission, tighter targets
Tests S5/T5 through S8/T15
"""

import subprocess
import re

COMMISSION = 1.24  # $0.62 each way on AMP

# Test matrix: (stop, target)
TESTS = [
    (5, 5), (5, 6), (5, 7), (5, 8),
    (6, 6), (6, 7), (6, 8), (6, 9), (6, 10),
    (7, 7), (7, 8), (7, 9), (7, 10),
    (8, 8), (8, 9), (8, 10),
]

results = []

print("="*70)
print(f"PARAMETER SWEEP: $1.24 RT Commission")
print("="*70)
print()

for stop, target in TESTS:
    print(f"Testing S{stop}/T{target}...", end=" ", flush=True)
    
    trail_activate = max(target - 1, stop)  # Trail activates 1pt before target
    
    cmd = [
        "python3", "backtest.py",
        "--symbol", "MNQ",
        "--interval", "1",
        "--stop", str(stop),
        "--target", str(target),
        "--trail-activate", str(trail_activate),
        "--trail-distance", "1"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    
    # Parse results
    trades_match = re.search(r"Trades:\s+(\d+)", output)
    wr_match = re.search(r"Win Rate:\s+([\d.]+)%", output)
    pnl_match = re.search(r"Total P&L:\s+([-\d.]+)\s+pts", output)
    
    if trades_match and wr_match and pnl_match:
        trades = int(trades_match.group(1))
        wr = float(wr_match.group(1))
        gross_pts = float(pnl_match.group(1))
        gross_pnl = gross_pts * 2  # MNQ = $2/pt
        commission = trades * COMMISSION
        net_pnl = gross_pnl - commission
        per_trade = net_pnl / trades if trades > 0 else 0
        
        results.append({
            "stop": stop,
            "target": target,
            "trades": trades,
            "wr": wr,
            "gross_pts": gross_pts,
            "gross_pnl": gross_pnl,
            "commission": commission,
            "net_pnl": net_pnl,
            "per_trade": per_trade
        })
        
        status = "✅" if net_pnl > 0 else "❌"
        print(f"{status} WR={wr:.1f}%, Net=${net_pnl:,.0f}, ${per_trade:.2f}/trade")
    else:
        print("❌ Failed to parse")

print()
print("="*70)
print("SWEEP RESULTS (sorted by Net P&L)")
print("="*70)
print(f"{'S/T':<8} {'Trades':>8} {'WR':>8} {'Gross':>12} {'Comm':>10} {'Net':>12} {'$/Trade':>10}")
print("-"*70)

for r in sorted(results, key=lambda x: -x["net_pnl"]):
    status = "✅" if r["net_pnl"] > 0 else "❌"
    print(f"{status} {r['stop']}/{r['target']:<4} {r['trades']:>8,} {r['wr']:>7.1f}% "
          f"${r['gross_pnl']:>10,.0f} ${r['commission']:>8,.0f} ${r['net_pnl']:>10,.0f} "
          f"${r['per_trade']:>8.2f}")

print("="*70)

# Best result
if results:
    best = max(results, key=lambda x: x["net_pnl"])
    print(f"\n🏆 BEST: S{best['stop']}/T{best['target']} — "
          f"Net ${best['net_pnl']:,.0f} ({best['wr']:.1f}% WR, ${best['per_trade']:.2f}/trade)")
    
    # Also show best $/trade
    best_per = max(results, key=lambda x: x["per_trade"])
    if best_per != best:
        print(f"💰 BEST $/TRADE: S{best_per['stop']}/T{best_per['target']} — "
              f"${best_per['per_trade']:.2f}/trade ({best_per['wr']:.1f}% WR)")
