#!/usr/bin/env python3
"""
DON Futures TopStep — RTH Only Backtesting

Run historical backtests on RTH data only (9:30 AM - 4:00 PM ET).
Designed for TopStep prop trading rules.

Usage:
    python backtest.py                    # Default: 1 year, 5-min
    python backtest.py --years 4          # 4 years of data
    python backtest.py --interval 15      # 15-minute bars
    python backtest.py --slippage 0.5     # Add slippage
    python backtest.py --full             # Year-by-year breakdown
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from bot import DonFuturesStrategy, DonFuturesConfig, VALIDATED_CONFIG, get_logger


def load_data(interval_minutes: int = 5, years: float = 1.0, symbol: str = "NQ") -> pd.DataFrame:
    """Load and resample futures data (NQ, MNQ, or ES)"""
    
    # Try multiple data sources based on symbol
    if symbol.upper() == "MNQ":
        data_paths = [
            'data/mnq 1 min data',  # New MNQ 1-min data (Databento format)
            'data/MNQ_1m.csv',
        ]
    elif symbol.upper() == "NQ":
        data_paths = [
            '/home/ubuntu/clawd/topstep/data/NQ_1m_7d.csv',
            '/home/ubuntu/clawd/topstep/data/NQ_5m_60d.csv',
            '/home/ubuntu/clawd/topstep/data/NQ_2m_60d.csv',
            '/home/ubuntu/clawd/topstep/data/NQ_1h_730d.csv',
            'data/NQ_5m.csv',
        ]
    else:  # ES
        data_paths = [
            '/home/ubuntu/clawd/topstep/data/ES_continuous_RTH_1m.csv',
            'data/ES_1m.csv',
            '../topstep/data/ES_continuous_RTH_1m.csv'
        ]
    
    df = None
    for path in data_paths:
        if os.path.exists(path):
            df = pd.read_csv(path)
            print(f"Loaded {symbol} data from: {path}")
            break
    
    if df is None:
        raise FileNotFoundError(f"No {symbol} data found.")
    
    # Normalize column names (handle various formats)
    df.columns = df.columns.str.lower()
    
    # Handle Databento format (ts_event column)
    if 'ts_event' in df.columns:
        df = df.rename(columns={'ts_event': 'timestamp'})
        # Filter to front-month contract only (highest volume per timestamp)
        # Group by timestamp and keep highest volume row
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.sort_values(['timestamp', 'volume'], ascending=[True, False])
        df = df.drop_duplicates(subset='timestamp', keep='first')
        print(f"  Filtered to front-month contracts: {len(df)} bars")
    elif 'datetime' in df.columns:
        df = df.rename(columns={'datetime': 'timestamp'})
    
    # Parse timestamps if not already datetime
    if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    df = df.set_index('timestamp')
    
    # Ensure we have OHLCV columns
    required = ['open', 'high', 'low', 'close']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    if 'volume' not in df.columns:
        df['volume'] = 0
    
    # Sort by timestamp
    df = df.sort_index()
    
    # Resample if needed
    if interval_minutes > 1:
        df = df.resample(f'{interval_minutes}min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
    
    # Filter to requested timeframe
    bars_per_year = int(252 * 6.5 * 60 / interval_minutes)  # Trading days * hours * minutes
    bars_needed = int(bars_per_year * years)
    df = df.tail(bars_needed)
    
    print(f"Data: {len(df)} bars, {df.index.min().date()} to {df.index.max().date()}")
    return df


def run_backtest(df: pd.DataFrame, config: DonFuturesConfig, 
                 slippage_pts: float = 0) -> dict:
    """Run backtest and return results"""
    
    # Create strategy (suppress logging for backtest)
    strategy = DonFuturesStrategy(config, "logs/backtest")
    
    trades = []
    
    for _, row in df.iterrows():
        bar = {
            'timestamp': row.name,
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'volume': row.get('volume', 0)
        }
        
        signal = strategy.add_bar(bar, 'backtest')
        
        if signal and signal['action'] == 'exit':
            # Apply slippage
            adj_pnl = signal['pnl_pts'] - slippage_pts
            trades.append({
                'timestamp': signal['timestamp'],
                'direction': signal['direction'],
                'entry_type': signal['entry_type'],
                'entry_price': signal['entry_price'],
                'exit_price': signal['exit_price'],
                'pnl_pts': adj_pnl,
                'pnl_dollars': adj_pnl * config.point_value,
                'reason': signal['reason']
            })
    
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'pnl_pts': 0, 'pnl_dollars': 0}
    
    wins = [t for t in trades if t['pnl_pts'] > 0]
    losses = [t for t in trades if t['pnl_pts'] <= 0]
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl_pts': sum(t['pnl_pts'] for t in trades),
        'pnl_dollars': sum(t['pnl_dollars'] for t in trades),
        'avg_win': np.mean([t['pnl_pts'] for t in wins]) if wins else 0,
        'avg_loss': np.mean([t['pnl_pts'] for t in losses]) if losses else 0,
        'trades_list': trades
    }


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='DON Futures Backtest')
    parser.add_argument('--symbol', type=str, default='NQ', help='Symbol: NQ, MNQ, or ES')
    parser.add_argument('--interval', type=int, default=5, help='Bar interval (minutes)')
    parser.add_argument('--years', type=float, default=1.0, help='Years of data')
    parser.add_argument('--slippage', type=float, default=0, help='Slippage in points')
    parser.add_argument('--full', action='store_true', help='Year-by-year breakdown')
    parser.add_argument('--failed-test', action='store_true', help='Enable failed test entries')
    parser.add_argument('--breakout', action='store_true', help='Enable breakout entries')
    parser.add_argument('--bounce', action='store_true', help='Enable bounce entries')
    parser.add_argument('--runner', action='store_true', help='Enable trailing stop')
    parser.add_argument('--no-runner', action='store_true', help='Disable trailing stop')
    parser.add_argument('--lag', type=int, default=0, help='Channel lag in bars')
    parser.add_argument('--lookback', type=int, default=10, help='Channel lookback period')
    parser.add_argument('--stop', type=float, default=4.0, help='Stop loss in points')
    parser.add_argument('--target', type=float, default=4.0, help='Target in points')
    parser.add_argument('--trail-activate', type=float, default=2.0, help='Trail activation pts')
    parser.add_argument('--trail-distance', type=float, default=1.5, help='Trail distance pts')
    return parser.parse_args()


def build_config(args) -> DonFuturesConfig:
    """Build strategy config from CLI args, inheriting defaults from VALIDATED_CONFIG."""
    return DonFuturesConfig(
        channel_period=args.lookback,
        channel_lag=args.lag,
        enable_failed_test=args.failed_test or VALIDATED_CONFIG.enable_failed_test,
        enable_breakout=args.breakout or VALIDATED_CONFIG.enable_breakout,
        enable_bounce=args.bounce or VALIDATED_CONFIG.enable_bounce,
        use_runner=not args.no_runner and (args.runner or VALIDATED_CONFIG.use_runner),
        trail_activation_pts=args.trail_activate,
        trail_distance_pts=args.trail_distance,
        stop_pts=args.stop,
        target_pts=args.target,
        # Inherit contract specs and TopStep settings
        tick_size=VALIDATED_CONFIG.tick_size,
        tick_value=VALIDATED_CONFIG.tick_value,
        point_value=VALIDATED_CONFIG.point_value,
        rth_only=VALIDATED_CONFIG.rth_only,
        rth_start=VALIDATED_CONFIG.rth_start,
        rth_end=VALIDATED_CONFIG.rth_end,
        flatten_before_close=VALIDATED_CONFIG.flatten_before_close,
        daily_loss_limit=VALIDATED_CONFIG.daily_loss_limit,
        max_trades_per_day=VALIDATED_CONFIG.max_trades_per_day,
        contracts=VALIDATED_CONFIG.contracts,
        account_size=VALIDATED_CONFIG.account_size
    )


def print_results(result: dict, trades_list: list = None, show_yearly: bool = False) -> None:
    """Print backtest results."""
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Trades:    {result['trades']}")
    print(f"Win Rate:  {result['win_rate']:.1f}%")
    print(f"Total P&L: {result['pnl_pts']:.1f} pts (${result['pnl_dollars']:,.0f})")
    print(f"Avg Win:   {result['avg_win']:.2f} pts")
    print(f"Avg Loss:  {result['avg_loss']:.2f} pts")
    
    if trades_list:
        print("\nExit Reasons:")
        for reason in ['target', 'trail_stop', 'stop', 'time', 'rth_flatten']:
            matching = [t for t in trades_list if t['reason'] == reason]
            if matching:
                count = len(matching)
                pnl = sum(t['pnl_pts'] for t in matching)
                print(f"  {reason:<12} {count:>5} trades  {pnl:>8.1f} pts")
    
    if show_yearly and trades_list:
        print("\n" + "="*60)
        print("YEAR-BY-YEAR BREAKDOWN")
        print("="*60)
        trades_df = pd.DataFrame(trades_list)
        trades_df['year'] = pd.to_datetime(trades_df['timestamp']).dt.year
        for year, group in trades_df.groupby('year'):
            wins = len(group[group['pnl_pts'] > 0])
            wr = wins / len(group) * 100
            pnl = group['pnl_dollars'].sum()
            print(f"{year}: {len(group):>5} trades | {wr:>5.1f}% WR | ${pnl:>10,.0f}")


def main():
    args = parse_args()
    
    print("="*60)
    print(f"DON FUTURES v1 — BACKTEST ({args.symbol.upper()})")
    print("="*60)
    
    df = load_data(args.interval, args.years, args.symbol)
    config = build_config(args)
    
    print(f"\nConfig:")
    print(f"  Failed Test: {config.enable_failed_test}")
    print(f"  Breakout:    {config.enable_breakout}")
    print(f"  Bounce:      {config.enable_bounce}")
    print(f"  Runner:      {config.use_runner}")
    
    print(f"\nRunning backtest (slippage: {args.slippage} pts)...")
    result = run_backtest(df, config, args.slippage)
    
    print_results(result, result.get('trades_list'), args.full)


if __name__ == '__main__':
    main()
