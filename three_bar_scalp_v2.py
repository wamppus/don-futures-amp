#!/usr/bin/env python3
"""
3 Bar Scalp Strategy - FAST VERSION
Vectorized for 2.8M row dataset
"""

import pandas as pd
import numpy as np
from datetime import time
import argparse

def load_data() -> pd.DataFrame:
    """Load and prep MNQ data"""
    print("Loading data...")
    df = pd.read_csv('data/mnq 1 min data')
    print(f"Loaded {len(df):,} bars")
    
    # Standardize columns
    df.columns = df.columns.str.lower()
    if 'ts_event' in df.columns:
        df['timestamp'] = pd.to_datetime(df['ts_event'])
    
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()


def calc_signals(df: pd.DataFrame, mode: str = "standard") -> pd.DataFrame:
    """Vectorized signal calculation"""
    
    if mode == "heikin_ashi":
        # Calculate HA candles
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_open = ((df['open'].shift(1) + df['close'].shift(1)) / 2).fillna(df['open'])
        # Smooth HA open
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        df['candle_dir'] = np.where(ha_close > ha_open, 1, np.where(ha_close < ha_open, -1, 0))
    else:
        # Standard candles
        df['candle_dir'] = np.where(df['close'] > df['open'], 1, 
                                    np.where(df['close'] < df['open'], -1, 0))
    
    # Check last 3 bars same direction
    df['bar1_dir'] = df['candle_dir'].shift(1)
    df['bar2_dir'] = df['candle_dir'].shift(2)
    df['bar3_dir'] = df['candle_dir'].shift(3)
    
    # Signal: all 3 bars same direction (1 or -1)
    df['signal'] = np.where(
        (df['bar1_dir'] == df['bar2_dir']) & 
        (df['bar2_dir'] == df['bar3_dir']) & 
        (df['bar1_dir'] != 0),
        df['bar1_dir'],
        0
    )
    
    # 3-bar range
    df['range_high'] = df['high'].rolling(3).max().shift(1)
    df['range_low'] = df['low'].rolling(3).min().shift(1)
    df['range_pts'] = df['range_high'] - df['range_low']
    
    return df


def backtest(df: pd.DataFrame, target: float = 5.0, stop: float = 4.0, 
             min_range: float = 2.0, use_runner: bool = True,
             trail_act: float = 4.0, trail_dist: float = 1.0) -> dict:
    """Fast backtest with simulated trade execution"""
    
    trades = []
    position = None
    
    signals = df[df['signal'] != 0].copy()
    signals = signals[signals['range_pts'] >= min_range]
    
    print(f"Found {len(signals):,} potential signals")
    
    for idx, row in signals.iterrows():
        # Skip if we have position (simplification: 1 position at a time)
        if position is not None:
            continue
        
        # Entry
        direction = 'long' if row['signal'] == 1 else 'short'
        entry = row['open']
        
        if direction == 'long':
            target_price = entry + target
            stop_price = entry - stop
        else:
            target_price = entry - target
            stop_price = entry + stop
        
        # Simulate exit on this bar or next bars
        # For speed, check if target/stop hit on same bar
        if direction == 'long':
            if row['high'] >= target_price:
                trades.append({'pnl': target, 'reason': 'target'})
                continue
            elif row['low'] <= stop_price:
                trades.append({'pnl': -stop, 'reason': 'stop'})
                continue
        else:
            if row['low'] <= target_price:
                trades.append({'pnl': target, 'reason': 'target'})
                continue
            elif row['high'] >= stop_price:
                trades.append({'pnl': -stop, 'reason': 'stop'})
                continue
        
        # Position still open - check next few bars (max 10)
        bar_idx = df.index.get_loc(idx)
        for i in range(1, min(11, len(df) - bar_idx)):
            next_bar = df.iloc[bar_idx + i]
            
            if direction == 'long':
                if next_bar['high'] >= target_price:
                    trades.append({'pnl': target, 'reason': 'target'})
                    break
                elif next_bar['low'] <= stop_price:
                    trades.append({'pnl': -stop, 'reason': 'stop'})
                    break
            else:
                if next_bar['low'] <= target_price:
                    trades.append({'pnl': target, 'reason': 'target'})
                    break
                elif next_bar['high'] >= stop_price:
                    trades.append({'pnl': -stop, 'reason': 'stop'})
                    break
        else:
            # Time exit after 10 bars
            exit_price = df.iloc[min(bar_idx + 10, len(df)-1)]['close']
            if direction == 'long':
                pnl = exit_price - entry
            else:
                pnl = entry - exit_price
            trades.append({'pnl': pnl, 'reason': 'time'})
    
    # Results
    if not trades:
        return {'trades': 0}
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in trades)
    
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'count': 0, 'pnl': 0}
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += t['pnl']
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'total_pnl_pts': total_pnl,
        'total_pnl_usd': total_pnl * 2,
        'avg_win': sum(t['pnl'] for t in wins) / len(wins) if wins else 0,
        'avg_loss': sum(t['pnl'] for t in losses) / len(losses) if losses else 0,
        'exit_reasons': reasons
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['standard', 'heikin_ashi'], default='standard')
    parser.add_argument('--target', type=float, default=5.0)
    parser.add_argument('--stop', type=float, default=4.0)
    parser.add_argument('--min-range', type=float, default=2.0)
    args = parser.parse_args()
    
    df = load_data()
    
    print(f"\nCalculating signals ({args.mode})...")
    df = calc_signals(df, args.mode)
    
    print(f"\nBacktesting: Target={args.target}, Stop={args.stop}, MinRange={args.min_range}")
    result = backtest(df, args.target, args.stop, args.min_range)
    
    print("\n" + "="*60)
    print(f"3 BAR SCALP RESULTS ({args.mode.upper()})")
    print("="*60)
    print(f"Trades:    {result['trades']:,}")
    print(f"Win Rate:  {result['win_rate']:.1f}%")
    print(f"Total P&L: {result['total_pnl_pts']:.1f} pts (${result['total_pnl_usd']:,.0f})")
    print(f"Avg Win:   {result['avg_win']:.2f} pts")
    print(f"Avg Loss:  {result['avg_loss']:.2f} pts")
    
    print("\nExit Reasons:")
    for reason, data in result.get('exit_reasons', {}).items():
        print(f"  {reason}: {data['count']:,} trades, {data['pnl']:.1f} pts")
    
    # Net after commission
    comm = result['trades'] * 1.24
    net = result['total_pnl_usd'] - comm
    print(f"\nAfter $1.24 commission:")
    print(f"  Commission: ${comm:,.0f}")
    print(f"  Net P&L:    ${net:,.0f}")
    if result['trades'] > 0:
        print(f"  Per Trade:  ${net/result['trades']:.2f}")
        print(f"  Per Day:    ${net/1260:.2f} (est 1260 trading days)")
