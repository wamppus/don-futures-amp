#!/usr/bin/env python3
"""
DON Futures TopStep — MNQ Trading Bot

Quick start:
    # Set credentials
    export PROJECTX_USERNAME="your_username"
    export PROJECTX_API_KEY="your_api_key"
    
    # Shadow mode (paper trading with live data)
    python run_topstep.py --mode shadow
    
    # Live mode (real trading)
    python run_topstep.py --mode live
"""

import asyncio
import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.dirname(__file__))

from bot.trading_bot import DONTradingBot
import argparse


async def main():
    parser = argparse.ArgumentParser(description='DON Futures TopStep - MNQ Bot')
    parser.add_argument(
        '--mode', 
        choices=['shadow', 'live'], 
        default='shadow',
        help='Trading mode: shadow (paper) or live (real money)'
    )
    args = parser.parse_args()
    
    print("="*60)
    print("DON FUTURES TOPSTEP - MNQ")
    print("="*60)
    print(f"Mode: {args.mode.upper()}")
    print()
    
    if args.mode == 'live':
        print("⚠️  LIVE TRADING MODE - REAL MONEY AT RISK")
        confirm = input("Type 'YES' to confirm: ")
        if confirm != 'YES':
            print("Aborted.")
            return
    
    bot = DONTradingBot(mode=args.mode)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        bot.stop()


if __name__ == '__main__':
    asyncio.run(main())
