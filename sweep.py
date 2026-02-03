#!/usr/bin/env python3
"""
Parameter Sweep - Find optimal target for AMP
Tests target 10-20 pts with stop 8
"""

import subprocess
import re

STOP = 8
TARGETS = range(10, 21)  # 10 to 20 inclusive
COMMISSION = 4.0  # AMP round-trip

results = []

print("="*70)
print(f"PARAMETER SWEEP: Stop={STOP}, Target=10-20")
print("="*70)
print()

for target in TARGETS:
    print(f"Testing S{STOP}/T{target}...", end=" ", flush=True)
    
    cmd = [
        "python3", "backtest.py",
        "--symbol", "MNQ",
        "--interval", "1",
        "--stop", str(STOP),
        "--target", str(target),
        "--trail-activate", str(target - 1),  # Trail activates 1pt before target
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
            "stop": STOP,
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
        print(f"{status} WR={wr:.1f}%, Net=${net_pnl:,.0f}")
    else:
        print("❌ Failed to parse")

print()
print("="*70)
print("SWEEP RESULTS (sorted by Net P&L)")
print("="*70)
print(f"{'S/T':<8} {'Trades':>8} {'WR':>8} {'Gross':>12} {'Comm':>12} {'Net':>12} {'$/Trade':>10}")
print("-"*70)

for r in sorted(results, key=lambda x: -x["net_pnl"]):
    status = "✅" if r["net_pnl"] > 0 else "❌"
    print(f"{status} {r['stop']}/{r['target']:<4} {r['trades']:>8,} {r['wr']:>7.1f}% "
          f"${r['gross_pnl']:>10,.0f} ${r['commission']:>10,.0f} ${r['net_pnl']:>10,.0f} "
          f"${r['per_trade']:>8.2f}")

print("="*70)

# Best result
if results:
    best = max(results, key=lambda x: x["net_pnl"])
    print(f"\n🏆 BEST: S{best['stop']}/T{best['target']} — "
          f"Net ${best['net_pnl']:,.0f} ({best['wr']:.1f}% WR, ${best['per_trade']:.2f}/trade)")
