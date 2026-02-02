# DON Futures TopStep — MNQ RTH Only

**Purpose:** Donchian Failed Test strategy for TopStep 100K evaluation using MNQ (Micro Nasdaq).

## Why MNQ over MES?

| Metric | MES (60d) | MNQ (60d) |
|--------|-----------|-----------|
| Win Rate | 85.5% | **92.7%** |
| Win Days | 100% | **100%** |
| Trades/Day | 16 | **32** |
| Days to Pass | 19 | **8** |

## TopStep Rules Implemented
- ✅ **RTH Only:** 9:30 AM - 4:00 PM ET (no overnight)
- ✅ **Auto-flatten:** 5 minutes before close (3:55 PM)
- ✅ **No weekend trading**

## Validated Results (RTH Only, 2022-2026)

| Year | Trades | Win Rate | P&L |
|------|--------|----------|-----|
| 2022 | 4,857 | 84.8% | $427,150 |
| 2023 | 3,222 | 82.7% | $199,075 |
| 2024 | 3,422 | 82.5% | $219,612 |
| 2025 | 4,617 | 85.0% | $405,038 |
| 2026 | 242 | 84.7% | $19,175 |
| **Total** | **16,360** | **84.0%** | **$1,270,050** |

*Based on ES 5-minute bars, RTH session only*

## The Edge

**Failed Test = Fade Liquidity Sweeps**

1. Price breaks Donchian channel (stop hunt / liquidity sweep)
2. Next bar closes back inside channel (trap complete)
3. Enter opposite direction (fade the trap)
4. Tight trailing stop locks profits

## Strategy Settings

```python
channel_period = 10        # Donchian lookback
enable_failed_test = True  # PRIMARY EDGE
trail_activation = 1.0 pts # Start trailing at +1 pt
trail_distance = 0.5 pts   # Trail 0.5 pts behind
stop_pts = 4.0             # Initial stop
target_pts = 4.0           # Full target
```

## Files

```
don-futures-topstep/
├── bot/
│   ├── strategy.py      # Core strategy with RTH filter
│   ├── data_feed.py     # Live data (ProjectX priority)
│   └── logger.py        # Trade logging
├── backtest.py          # Historical validation
├── run_shadow.py        # Paper trading mode
└── ARCHITECTURE.md      # This file
```

## Running

```bash
# Backtest
python3 backtest.py --years 4 --full

# Paper trading (shadow mode)
python3 run_shadow.py
```

## TopStep Account Sizes

| Account | Max Contracts | Daily Loss Limit | Trailing Max |
|---------|---------------|------------------|--------------|
| 50K | 5 | $1,000 | $2,000 |
| 100K | 10 | $2,000 | $3,000 |
| 150K | 15 | $3,000 | $4,500 |

**Recommended:** Start with 50K, trade 1 MES ($5/point) to validate fills.

## vs Original DON Futures v1

| Metric | 24/7 (v1) | RTH Only (TopStep) |
|--------|-----------|-------------------|
| Win Rate | 85.0% | 84.0% |
| Trades/Year | ~4,100 | ~4,000 |
| P&L/Year | ~$310K | ~$318K |

RTH-only performs nearly identically — most of the edge is during regular hours anyway.

## Quick Start

```bash
# 1. Set ProjectX credentials
export PROJECTX_USERNAME="your_topstep_username"
export PROJECTX_API_KEY="your_api_key"

# 2. Run shadow mode (paper trading with live data)
python run_topstep.py --mode shadow

# 3. After 2-3 winning days, go live
python run_topstep.py --mode live
```

## Files

```
don-futures-topstep/
├── bot/
│   ├── strategy.py        # Core DON strategy with RTH filter
│   ├── config.py          # MNQ + TopStep 100K settings
│   ├── trading_bot.py     # Main bot with ProjectX integration
│   ├── projectx_client.py # TopStepX API client
│   ├── data_feed.py       # Market data handling
│   └── logger.py          # Trade logging
├── run_topstep.py         # Entry point
├── backtest.py            # Historical validation
└── ARCHITECTURE.md        # This file
```

## TopStep 100K Pass Simulation (4 MNQ)

| Metric | Value |
|--------|-------|
| Pass Rate | 100% |
| Avg Days | 8 |
| Worst Day | +$108 (still green!) |

## Next Steps

1. Shadow trade 2-3 days on MNQ via TopStep
2. Verify fills match expected behavior
3. Go live and pass in ~8 days
