# 3 Bar Scalp Strategy

**Created:** 2026-02-03
**Status:** BACKTEST VALIDATED
**Instrument:** MNQ (Micro Nasdaq Futures)
**Broker:** AMP Futures
**Commission:** $1.24 RT ($0.62 each way)

---

## Strategy Logic

### Entry Rules
1. Look at the last 3 completed bars
2. If all 3 bars are the **same color** (direction):
   - 3 GREEN bars (close > open) → **LONG** on bar 4 open
   - 3 RED bars (close < open) → **SHORT** on bar 4 open
3. Minimum 3-bar range filter: 2.0 pts (to avoid chop)

### Exit Rules
- **Target:** 5 pts (+$10 on MNQ)
- **Stop:** 4 pts (-$8 on MNQ)
- **Time Exit:** 10 bars max hold
- **Runner (optional):** Trail activation at 4 pts, 1 pt distance

### Direction Modes
| Mode | Description |
|------|-------------|
| **Standard** | Uses raw OHLC candles |
| **Heikin Ashi** | Uses smoothed HA candles (fewer signals, potentially cleaner) |

---

## Backtest Results (5 Years MNQ 1-Min Data)

### Standard Mode - S4/T5
```
Period:      Feb 2021 → Feb 2026 (5 years)
Bars:        2,814,223
Trades:      524,489 (416/day average)
Win Rate:    56.2%
Gross P&L:   $1,104,831
Commission:  $650,366
NET P&L:     $454,465
Per Trade:   $0.87
PER DAY:     $360.69
```

### Exit Breakdown
| Exit Type | Trades | P&L (pts) |
|-----------|--------|-----------|
| Target | 292,040 | +1,460,200 |
| Stop | 227,327 | -909,308 |
| Time | 5,122 | +1,524 |

---

## Configuration

### Validated Settings
```python
# Entry
mode = "standard"           # or "heikin_ashi"
min_3bar_range_pts = 2.0    # Filter out low-range setups

# Exit
target_pts = 5.0            # +$10 gross, +$8.76 net
stop_pts = 4.0              # -$8 gross, -$9.24 net
max_hold_bars = 10          # Time exit

# Runner (optional)
use_runner = True
trail_activation_pts = 4.0
trail_distance_pts = 1.0
```

### P&L Math (1 MNQ)
```
Win:  +5 pts × $2 = +$10 - $1.24 comm = +$8.76 net
Loss: -4 pts × $2 = -$8  - $1.24 comm = -$9.24 net

At 56.2% WR:
EV = (0.562 × $8.76) + (0.438 × -$9.24)
EV = $4.92 - $4.05 = +$0.87/trade
```

---

## Comparison: 3 Bar Scalp vs DON Failed Test

| Metric | 3 Bar Scalp | DON Failed Test |
|--------|-------------|-----------------|
| Trades/day | **416** | 14 |
| Win Rate | 56.2% | 55.7% |
| Per trade | $0.87 | $0.88 |
| **Net/day** | **$360** | $12 |
| Net/year | **$90,720** | $3,024 |

**Key insight:** Similar edge per trade, but 30x more opportunities.

---

## Scaling Projections

### Conservative (1 MNQ)
| Timeframe | Net P&L |
|-----------|---------|
| Daily | $360 |
| Weekly | $1,800 |
| Monthly | $7,560 |
| Yearly | $90,720 |

### Scaled (4 MNQ)
| Timeframe | Net P&L |
|-----------|---------|
| Daily | $1,440 |
| Weekly | $7,200 |
| Monthly | $30,240 |
| Yearly | $362,880 |

---

## Risk Considerations

1. **Commission Impact:** 59% of gross profit goes to commissions
   - Lower commission = significantly more profit
   - Consider volume tiers or different broker

2. **Slippage:** Not accounted for in backtest
   - Fast entries on bar open may slip
   - Estimate 0.25-0.5 pts slippage per trade

3. **Market Conditions:** 
   - Works best in trending/momentum markets
   - May struggle in choppy/ranging conditions

4. **Execution Speed:**
   - 416 trades/day = ~1 trade every 1.5 minutes
   - Needs fast, reliable execution

5. **Drawdowns:**
   - Not calculated in current backtest
   - Need to add max drawdown analysis

---

## Implementation Notes

### Files
- `three_bar_scalp.py` - Original implementation (slow)
- `three_bar_scalp_v2.py` - Optimized backtester (fast)

### Data
- Source: Databento MNQ 1-min data
- Location: `data/mnq 1 min data`
- Period: Feb 2021 - Feb 2026
- Bars: 2,814,223

### To Build Live Bot
1. Create `three_bar_bot.py` with:
   - Real-time bar feed (ProjectX or AMP API)
   - Signal detection on bar close
   - Order execution on next bar open
   - Position tracking
   - P&L logging
   
2. GUI integration:
   - Display last 3 bars
   - Show signal direction
   - Track open position
   - Daily P&L

---

## Next Steps

- [ ] Test Heikin Ashi mode (in progress)
- [ ] Add max drawdown calculation
- [ ] Test different target/stop combos (sweep)
- [ ] Add slippage simulation
- [ ] Build live trading bot
- [ ] Paper trade for validation

---

## Version History

| Date | Change |
|------|--------|
| 2026-02-03 | Initial strategy concept and backtest |
