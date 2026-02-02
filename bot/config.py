"""
DON Futures TopStep - MNQ Configuration
Optimized for TopStep 100K evaluation with MNQ (Micro Nasdaq)
"""

from datetime import time

# =============================================================================
# INSTRUMENT (MNQ - Micro Nasdaq)
# =============================================================================

INSTRUMENT = {
    "symbol": "NQ",                 # Nasdaq futures
    "contract_type": "MNQ",         # Micro contract
    "symbol_id": "F.US.ENQ",        # ProjectX symbol ID for MNQ
    "tick_size": 0.25,              # MNQ tick size
    "tick_value": 0.50,             # MNQ = $0.50/tick
    "point_value": 2.0,             # MNQ = $2/point
}

# =============================================================================
# DON STRATEGY PARAMETERS (VALIDATED)
# =============================================================================

STRATEGY = {
    # Channel
    "channel_period": 10,           # Donchian lookback
    "channel_lag": 0,               # Bars to lag channel calc (0=current, 5=5 bars ago)
    
    # Entry types
    "enable_failed_test": True,     # PRIMARY EDGE - 92.7% WR on NQ
    "enable_bounce": False,
    "enable_breakout": True,        # Trend breakout enabled
    
    # Failed test tolerance
    "touch_tolerance_pts": 1.0,
    
    # Risk management (points) - AMP 24/7 MODE
    "stop_pts": 8.0,                # -$16 (-$20 after $4 commission)
    "target_pts": 12.0,             # +$24 (+$20 after $4 commission)
    
    # Runner settings - lock profits at 11pts, tight trail
    "use_runner": True,
    "trail_activation_pts": 11.0,   # Activate trail at +11 pts (near target)
    "trail_distance_pts": 1.0,      # Trail 1 pt behind (tight, lock it in)
    
    # Time exit
    "max_hold_bars": 5,
}

# =============================================================================
# SESSION TIMES - AMP 24/7 MODE
# =============================================================================

SESSIONS = {
    "rth_start": time(18, 0),       # 6:00 PM ET Sunday (futures open)
    "rth_end": time(17, 0),         # 5:00 PM ET Friday (futures close)
    "flatten_before_close": 5,      # Flatten 5 min before close
    "trade_rth_only": False,        # AMP = trade anytime futures are open
    "timezone": "America/New_York",
}

# =============================================================================
# TOPSTEP 100K RULES
# =============================================================================

TOPSTEP = {
    "account_size": "100K",
    "profit_target": 6000,          # Pass threshold
    "max_trailing_dd": 3000,        # Max trailing drawdown
    "daily_loss_limit": 2000,       # TopStep daily limit
    "max_contracts": 10,            # Position limit
}

# =============================================================================
# POSITION SIZING (Optimized for fast pass)
# =============================================================================

TRADING = {
    "contracts": 4,                 # 4 MNQ = ~8 days to pass
    "timeframe": "1min",            # 1-minute bars
    "timeframe_minutes": 1,         # For API calls
}

# =============================================================================
# RISK MANAGEMENT (Conservative - 50% of TopStep limits)
# =============================================================================

RISK = {
    "daily_loss_limit": 1000.0,     # Stop at $1K (50% of $2K TopStep limit)
    "max_daily_trades": 25,         # Cap trades per session
    "max_consecutive_losses": 7,    # Pause after 7 consecutive losses
}

# =============================================================================
# LOGGING
# =============================================================================

LOGGING = {
    "log_level": "INFO",
    "log_dir": "logs",
    "trade_log": "logs/trades.csv",
}

# =============================================================================
# VALIDATED BACKTEST RESULTS (60-day NQ sample)
# =============================================================================

BACKTEST_RESULTS = {
    "mode": "AMP 24/7",
    "settings": "S8/T12, Trail@11, Dist=1",
    "win_rate": 0.65,               # Conservative estimate
    "net_per_win": 20,              # $24 - $4 commission
    "net_per_loss": -20,            # -$16 - $4 commission
    "ev_per_trade": 6,              # 0.65*20 - 0.35*20
    "note": "Let it run 23hrs/day, print money",
}
