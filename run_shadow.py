#!/usr/bin/env python3
"""
DON Futures v1 — Shadow Trading Mode

Paper trades with live data. NO REAL ORDERS.
Logs everything for validation before going live.

Usage:
    python run_shadow.py
    python run_shadow.py --symbol MES --interval 5
"""

import os
import sys
import argparse
import signal
from datetime import datetime, timedelta
import time

# Add bot to path
sys.path.insert(0, os.path.dirname(__file__))

from bot import (
    DonFuturesStrategy, VALIDATED_CONFIG,
    create_data_feed, get_logger
)


class ShadowTrader:
    """
    Shadow/paper trading runner
    
    - Connects to live data feed
    - Runs strategy in paper mode
    - Logs ALL signals and trades
    - No real order execution
    """
    
    def __init__(self, symbol: str = "ES", interval: int = 5):
        self.symbol = symbol
        self.interval = interval
        
        self.logger = get_logger("logs")
        self.logger.info("="*60)
        self.logger.info("DON FUTURES v1 — SHADOW MODE")
        self.logger.info("="*60)
        self.logger.info(f"Symbol: {symbol}")
        self.logger.info(f"Interval: {interval} minutes")
        self.logger.info("⚠️  PAPER TRADING — NO REAL ORDERS")
        self.logger.info("="*60)
        
        # Initialize strategy
        self.strategy = DonFuturesStrategy(VALIDATED_CONFIG, "logs")
        
        # Initialize data feed
        self.feed = create_data_feed({
            'symbol': symbol,
            'bar_interval': interval,
            'projectx_username': os.getenv('PROJECTX_USERNAME'),
            'projectx_api_key': os.getenv('PROJECTX_API_KEY')
        })
        
        # Register callbacks
        self.feed.on_bar(self._on_bar)
        
        self.running = False
    
    def _on_bar(self, bar):
        """Process new bar through strategy"""
        signal = self.strategy.add_bar(bar.to_dict(), bar.source)
        
        if signal:
            if signal['action'] == 'entry':
                self.logger.info(f"🎯 SHADOW ENTRY: {signal['direction'].upper()} @ {signal['price']:.2f}")
            elif signal['action'] == 'exit':
                self.logger.info(f"{'✅' if signal['pnl_pts'] > 0 else '❌'} SHADOW EXIT: {signal['pnl_pts']:+.2f} pts")
    
    def warmup(self):
        """Load historical bars for indicator warmup"""
        self.logger.info("Loading historical bars for warmup...")
        
        bars = self.feed.fetch_historical(count=50)
        for bar in bars:
            self.strategy.add_bar(bar.to_dict(), 'historical')
        
        self.logger.info(f"Warmup complete: {len(bars)} bars loaded")
    
    def run(self):
        """Main run loop"""
        self.running = True
        
        # Warmup with historical data
        self.warmup()
        
        # Start live feed
        self.logger.info("Starting live data feed...")
        self.feed.start()
        
        self.logger.info("Shadow trading active. Press Ctrl+C to stop.")
        
        try:
            while self.running:
                time.sleep(1)
                
                # Periodic status
                status = self.strategy.get_status()
                if status['in_position']:
                    self.logger.debug(f"Position: {status['direction']} @ {status['entry_price']:.2f}")
                    
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested...")
        
        self.stop()
    
    def stop(self):
        """Clean shutdown"""
        self.running = False
        self.feed.stop()
        self.strategy.shutdown()
        self.logger.info("Shadow trader stopped.")


def main():
    parser = argparse.ArgumentParser(description='DON Futures Shadow Trading')
    parser.add_argument('--symbol', type=str, default='ES', help='Symbol (ES, MES)')
    parser.add_argument('--interval', type=int, default=5, help='Bar interval in minutes')
    args = parser.parse_args()
    
    # Handle Ctrl+C gracefully
    trader = ShadowTrader(args.symbol, args.interval)
    
    def signal_handler(sig, frame):
        trader.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    trader.run()


if __name__ == '__main__':
    main()
