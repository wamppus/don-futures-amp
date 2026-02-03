#!/usr/bin/env python3
"""
3 Bar Scalp Strategy

Logic:
1. Look at last 3 bars
2. Determine direction (standard or Heikin Ashi)
3. Enter on bar 4 open in that direction
4. Target: 4-6 pts, with runner option
5. Stop: Below/above 3-bar range OR fixed pts

Two modes:
- STANDARD: 3 consecutive same-color candles
- HEIKIN ASHI: 3 consecutive HA candles same direction
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Literal
from datetime import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


@dataclass
class ScalpConfig:
    # Direction mode
    mode: Literal["standard", "heikin_ashi"] = "standard"
    
    # Entry rules
    min_3bar_range_pts: float = 2.0  # Minimum range of 3 bars to qualify
    
    # Exit rules
    target_pts: float = 5.0
    stop_mode: Literal["fixed", "range"] = "fixed"  # fixed pts or 3-bar range
    fixed_stop_pts: float = 4.0
    
    # Runner
    use_runner: bool = True
    trail_activation_pts: float = 4.0
    trail_distance_pts: float = 1.0
    
    # Session
    rth_only: bool = False
    rth_start: time = time(9, 30)
    rth_end: time = time(16, 0)


@dataclass
class Position:
    direction: str  # "long" or "short"
    entry_price: float
    entry_bar: int
    stop: float
    target: float
    trail_stop: Optional[float] = None
    
    @property
    def effective_stop(self) -> float:
        if self.trail_stop is None:
            return self.stop
        if self.direction == "long":
            return max(self.stop, self.trail_stop)
        else:
            return min(self.stop, self.trail_stop)


def calc_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Convert OHLC to Heikin Ashi"""
    ha = df.copy()
    
    # HA Close = (O + H + L + C) / 4
    ha['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    
    # HA Open = (prev HA Open + prev HA Close) / 2
    ha['ha_open'] = 0.0
    ha.iloc[0, ha.columns.get_loc('ha_open')] = (df.iloc[0]['open'] + df.iloc[0]['close']) / 2
    
    for i in range(1, len(ha)):
        ha.iloc[i, ha.columns.get_loc('ha_open')] = (
            ha.iloc[i-1]['ha_open'] + ha.iloc[i-1]['ha_close']
        ) / 2
    
    # HA High = max(H, HA Open, HA Close)
    ha['ha_high'] = ha[['high', 'ha_open', 'ha_close']].max(axis=1)
    
    # HA Low = min(L, HA Open, HA Close)
    ha['ha_low'] = ha[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    return ha


def get_direction(bars: pd.DataFrame, mode: str) -> Optional[str]:
    """
    Determine direction from last 3 bars
    Returns 'long', 'short', or None
    """
    if len(bars) < 3:
        return None
    
    last3 = bars.iloc[-3:]
    
    if mode == "standard":
        # Standard: 3 consecutive same-color candles
        colors = []
        for _, bar in last3.iterrows():
            if bar['close'] > bar['open']:
                colors.append('green')
            elif bar['close'] < bar['open']:
                colors.append('red')
            else:
                colors.append('neutral')
        
        if all(c == 'green' for c in colors):
            return 'long'
        elif all(c == 'red' for c in colors):
            return 'short'
        return None
    
    elif mode == "heikin_ashi":
        # Heikin Ashi: 3 consecutive HA candles same direction
        colors = []
        for _, bar in last3.iterrows():
            if bar['ha_close'] > bar['ha_open']:
                colors.append('green')
            elif bar['ha_close'] < bar['ha_open']:
                colors.append('red')
            else:
                colors.append('neutral')
        
        if all(c == 'green' for c in colors):
            return 'long'
        elif all(c == 'red' for c in colors):
            return 'short'
        return None
    
    return None


def run_backtest(df: pd.DataFrame, config: ScalpConfig) -> dict:
    """Run 3 bar scalp backtest"""
    
    # Add Heikin Ashi if needed
    if config.mode == "heikin_ashi":
        df = calc_heikin_ashi(df)
    
    position: Optional[Position] = None
    trades = []
    bar_count = 0
    
    for i in range(3, len(df)):
        bar = df.iloc[i]
        prev_bars = df.iloc[i-3:i]
        
        bar_count += 1
        price = bar['close']
        
        # RTH filter
        if config.rth_only and 'timestamp' in bar:
            bar_time = pd.to_datetime(bar['timestamp']).time()
            if bar_time < config.rth_start or bar_time >= config.rth_end:
                continue
        
        # Check exits first
        if position:
            is_long = position.direction == "long"
            effective_stop = position.effective_stop
            
            # Target hit
            if is_long and bar['high'] >= position.target:
                pnl = position.target - position.entry_price
                trades.append({
                    'direction': position.direction,
                    'entry': position.entry_price,
                    'exit': position.target,
                    'pnl_pts': pnl,
                    'reason': 'target'
                })
                position = None
                continue
            elif not is_long and bar['low'] <= position.target:
                pnl = position.entry_price - position.target
                trades.append({
                    'direction': position.direction,
                    'entry': position.entry_price,
                    'exit': position.target,
                    'pnl_pts': pnl,
                    'reason': 'target'
                })
                position = None
                continue
            
            # Stop hit
            if is_long and bar['low'] <= effective_stop:
                pnl = effective_stop - position.entry_price
                reason = 'trail_stop' if position.trail_stop else 'stop'
                trades.append({
                    'direction': position.direction,
                    'entry': position.entry_price,
                    'exit': effective_stop,
                    'pnl_pts': pnl,
                    'reason': reason
                })
                position = None
                continue
            elif not is_long and bar['high'] >= effective_stop:
                pnl = position.entry_price - effective_stop
                reason = 'trail_stop' if position.trail_stop else 'stop'
                trades.append({
                    'direction': position.direction,
                    'entry': position.entry_price,
                    'exit': effective_stop,
                    'pnl_pts': pnl,
                    'reason': reason
                })
                position = None
                continue
            
            # Update trailing stop
            if config.use_runner:
                if is_long:
                    unrealized = bar['high'] - position.entry_price
                    if unrealized >= config.trail_activation_pts:
                        new_trail = bar['high'] - config.trail_distance_pts
                        if position.trail_stop is None or new_trail > position.trail_stop:
                            position.trail_stop = new_trail
                else:
                    unrealized = position.entry_price - bar['low']
                    if unrealized >= config.trail_activation_pts:
                        new_trail = bar['low'] + config.trail_distance_pts
                        if position.trail_stop is None or new_trail < position.trail_stop:
                            position.trail_stop = new_trail
        
        # Check entries (only if no position)
        if position is None:
            direction = get_direction(prev_bars, config.mode)
            
            if direction:
                # Calculate 3-bar range
                range_high = prev_bars['high'].max()
                range_low = prev_bars['low'].min()
                range_pts = range_high - range_low
                
                # Filter: minimum range
                if range_pts < config.min_3bar_range_pts:
                    continue
                
                # Entry on bar open
                entry = bar['open']
                
                # Calculate stop
                if config.stop_mode == "fixed":
                    if direction == "long":
                        stop = entry - config.fixed_stop_pts
                    else:
                        stop = entry + config.fixed_stop_pts
                else:  # range
                    if direction == "long":
                        stop = range_low - 0.25  # Just below range
                    else:
                        stop = range_high + 0.25  # Just above range
                
                # Calculate target
                if direction == "long":
                    target = entry + config.target_pts
                else:
                    target = entry - config.target_pts
                
                position = Position(
                    direction=direction,
                    entry_price=entry,
                    entry_bar=bar_count,
                    stop=stop,
                    target=target
                )
    
    # Calculate results
    if not trades:
        return {"trades": 0, "win_rate": 0, "total_pnl": 0}
    
    wins = [t for t in trades if t['pnl_pts'] > 0]
    losses = [t for t in trades if t['pnl_pts'] <= 0]
    
    total_pnl = sum(t['pnl_pts'] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    avg_win = sum(t['pnl_pts'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pts'] for t in losses) / len(losses) if losses else 0
    
    # Exit reasons
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'count': 0, 'pnl': 0}
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += t['pnl_pts']
    
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_pnl_pts": total_pnl,
        "total_pnl_usd": total_pnl * 2,  # MNQ = $2/pt
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "exit_reasons": reasons
    }


def load_data(filepath: str = "data/mnq 1 min data") -> pd.DataFrame:
    """Load MNQ data"""
    df = pd.read_csv(filepath)
    
    # Normalize column names
    df.columns = df.columns.str.lower().str.strip()
    
    # Handle different column name formats
    col_map = {
        'datetime': 'timestamp',
        'date': 'timestamp', 
        'time': 'timestamp',
    }
    df.rename(columns=col_map, inplace=True)
    
    return df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="3 Bar Scalp Backtest")
    parser.add_argument('--mode', choices=['standard', 'heikin_ashi'], default='standard')
    parser.add_argument('--target', type=float, default=5.0)
    parser.add_argument('--stop', type=float, default=4.0)
    parser.add_argument('--min-range', type=float, default=2.0)
    parser.add_argument('--runner', action='store_true', default=True)
    parser.add_argument('--no-runner', action='store_true')
    args = parser.parse_args()
    
    print("Loading data...")
    df = load_data()
    print(f"Loaded {len(df):,} bars")
    
    config = ScalpConfig(
        mode=args.mode,
        target_pts=args.target,
        fixed_stop_pts=args.stop,
        min_3bar_range_pts=args.min_range,
        use_runner=not args.no_runner
    )
    
    print(f"\nConfig:")
    print(f"  Mode: {config.mode}")
    print(f"  Target: {config.target_pts} pts")
    print(f"  Stop: {config.fixed_stop_pts} pts")
    print(f"  Min Range: {config.min_3bar_range_pts} pts")
    print(f"  Runner: {config.use_runner}")
    
    print("\nRunning backtest...")
    result = run_backtest(df, config)
    
    print("\n" + "="*60)
    print("RESULTS - 3 BAR SCALP")
    print("="*60)
    print(f"Trades:    {result['trades']:,}")
    print(f"Win Rate:  {result['win_rate']:.1f}%")
    print(f"Total P&L: {result['total_pnl_pts']:.1f} pts (${result['total_pnl_usd']:,.0f})")
    print(f"Avg Win:   {result['avg_win']:.2f} pts")
    print(f"Avg Loss:  {result['avg_loss']:.2f} pts")
    
    print("\nExit Reasons:")
    for reason, data in result.get('exit_reasons', {}).items():
        print(f"  {reason}: {data['count']} trades, {data['pnl']:.1f} pts")
    
    # Commission calc
    commission = result['trades'] * 1.24
    net = result['total_pnl_usd'] - commission
    print(f"\nAfter $1.24 commission:")
    print(f"  Commission: ${commission:,.0f}")
    print(f"  Net P&L:    ${net:,.0f}")
    print(f"  Per Trade:  ${net/result['trades']:.2f}" if result['trades'] > 0 else "")
