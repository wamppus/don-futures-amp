#!/usr/bin/env python3
"""
DON Futures TopStep Trading Bot
MNQ trading via ProjectX/TopStepX API

Usage:
    python trading_bot.py --mode shadow    # Paper trade with live data
    python trading_bot.py --mode live      # Live trading (after validation)
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, time
from typing import Optional
import pandas as pd
import pytz

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.config import INSTRUMENT, STRATEGY, SESSIONS, TOPSTEP, TRADING, RISK, LOGGING
from bot.strategy import DonFuturesStrategy, DonFuturesConfig, Direction
from bot.projectx_client import ProjectXClient, OrderSide, OrderType

# Timezone
ET = pytz.timezone("America/New_York")

# Setup logging
os.makedirs(LOGGING['log_dir'], exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOGGING['log_level']),
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{LOGGING['log_dir']}/bot_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)


class DONTradingBot:
    """DON Futures Trading Bot for TopStep MNQ"""
    
    def __init__(self, mode: str = 'shadow'):
        self.mode = mode
        self.is_running = False
        
        # Build strategy config from settings
        self.strategy_config = DonFuturesConfig(
            channel_period=STRATEGY['channel_period'],
            enable_failed_test=STRATEGY['enable_failed_test'],
            enable_bounce=STRATEGY['enable_bounce'],
            enable_breakout=STRATEGY['enable_breakout'],
            touch_tolerance_pts=STRATEGY['touch_tolerance_pts'],
            stop_pts=STRATEGY['stop_pts'],
            target_pts=STRATEGY['target_pts'],
            use_runner=STRATEGY['use_runner'],
            trail_activation_pts=STRATEGY['trail_activation_pts'],
            trail_distance_pts=STRATEGY['trail_distance_pts'],
            max_bars=STRATEGY['max_hold_bars'],
            tick_size=INSTRUMENT['tick_size'],
            tick_value=INSTRUMENT['tick_value'],
            point_value=INSTRUMENT['point_value'],
            rth_only=SESSIONS['trade_rth_only'],
            rth_start=SESSIONS['rth_start'],
            rth_end=SESSIONS['rth_end'],
            flatten_before_close=SESSIONS['flatten_before_close'],
            daily_loss_limit=RISK['daily_loss_limit'],
            max_trades_per_day=RISK['max_daily_trades'],
            contracts=TRADING['contracts'],
        )
        
        self.strategy = DonFuturesStrategy(self.strategy_config, LOGGING['log_dir'])
        
        # Position tracking
        self.position = 0  # 1 = long, -1 = short, 0 = flat
        self.position_entry_price = 0.0
        
        # ProjectX client
        self.projectx: Optional[ProjectXClient] = None
        self.account_id: Optional[int] = None
        self.contract_id: Optional[str] = None
        
        # Stats
        self.session_trades = 0
        self.session_pnl = 0.0
        
        logger.info(f"DON Trading Bot initialized in {mode} mode")
        logger.info(f"Instrument: {INSTRUMENT['contract_type']} ({INSTRUMENT['symbol']})")
        logger.info(f"Contracts: {TRADING['contracts']} @ ${INSTRUMENT['point_value']}/pt")
    
    async def connect_projectx(self) -> bool:
        """Connect to ProjectX API"""
        username = os.environ.get("PROJECTX_USERNAME")
        api_key = os.environ.get("PROJECTX_API_KEY")
        
        if not username or not api_key:
            logger.error("Set PROJECTX_USERNAME and PROJECTX_API_KEY environment variables")
            return False
        
        self.projectx = ProjectXClient(username, api_key)
        
        if not await self.projectx.connect():
            logger.error("Failed to connect to ProjectX")
            return False
        
        logger.info("Connected to ProjectX")
        
        # Get accounts
        accounts = await self.projectx.get_accounts()
        if not accounts:
            logger.error("No accounts found")
            return False
        
        # Use first account (or find specific one)
        self.account_id = accounts[0]['id']
        logger.info(f"Using account: {accounts[0].get('name')} (ID: {self.account_id})")
        
        # Find MNQ contract
        contracts = await self.projectx.get_contracts(live=False)
        for c in contracts:
            if c.get('symbolId') == INSTRUMENT['symbol_id']:
                self.contract_id = c['id']
                logger.info(f"Found contract: {c.get('description')} ({self.contract_id})")
                break
        
        if not self.contract_id:
            # Try to find any NQ contract
            for c in contracts:
                if 'ENQ' in c.get('symbolId', '') or 'NQ' in c.get('id', ''):
                    self.contract_id = c['id']
                    logger.info(f"Found NQ contract: {c.get('description')} ({self.contract_id})")
                    break
        
        if not self.contract_id:
            logger.error(f"Could not find MNQ contract (looking for {INSTRUMENT['symbol_id']})")
            logger.info("Available contracts:")
            for c in contracts[:20]:
                logger.info(f"  {c.get('symbolId')} - {c.get('description')}")
            return False
        
        return True
    
    def is_rth(self) -> bool:
        """Check if currently in RTH"""
        now = datetime.now(ET)
        current_time = now.time()
        
        # Check weekday
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        
        return SESSIONS['rth_start'] <= current_time < SESSIONS['rth_end']
    
    async def get_current_bars(self, lookback: int = 50) -> pd.DataFrame:
        """Get recent bars from ProjectX"""
        if not self.projectx or not self.contract_id:
            return pd.DataFrame()
        
        # Get timeframe from config (default 1 minute)
        tf_minutes = TRADING.get('timeframe_minutes', 1)
        
        end_time = datetime.utcnow()
        # Calculate start time based on actual timeframe
        start_time = end_time - timedelta(minutes=lookback * tf_minutes + 60)
        
        bars = await self.projectx.get_bars(
            contract_id=self.contract_id,
            start_time=start_time,
            end_time=end_time,
            unit=2,  # Minute
            unit_number=tf_minutes,  # Use config timeframe
            limit=lookback,
            live=False
        )
        
        if not bars:
            return pd.DataFrame()
        
        df = pd.DataFrame(bars)
        df['timestamp'] = pd.to_datetime(df['t'], utc=True)
        df['open'] = df['o']
        df['high'] = df['h']
        df['low'] = df['l']
        df['close'] = df['c']
        df['volume'] = df['v']
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    async def place_order(self, direction: Direction, reason: str) -> bool:
        """Place order via ProjectX"""
        if self.mode == 'shadow':
            logger.info(f"[SHADOW] Would place {direction.name} order: {reason}")
            return True
        
        if not self.projectx:
            logger.error("ProjectX not connected")
            return False
        
        side = OrderSide.BID if direction == Direction.LONG else OrderSide.ASK
        
        result = await self.projectx.place_order(
            account_id=self.account_id,
            contract_id=self.contract_id,
            side=side,
            order_type=OrderType.MARKET,
            size=TRADING['contracts'],
            custom_tag=f"DON_{reason}_{datetime.now().strftime('%H%M%S')}"
        )
        
        if result.get('success', False) or result.get('orderId'):
            logger.info(f"Order placed: {direction.name} {TRADING['contracts']} MNQ")
            return True
        else:
            logger.error(f"Order failed: {result.get('errorMessage')}")
            return False
    
    async def close_position(self, reason: str) -> bool:
        """Close current position"""
        if self.position == 0:
            return True
        
        if self.mode == 'shadow':
            logger.info(f"[SHADOW] Would close position: {reason}")
            self.position = 0
            return True
        
        if not self.projectx:
            return False
        
        result = await self.projectx.close_position(
            account_id=self.account_id,
            contract_id=self.contract_id
        )
        
        if result.get('success', False) or result.get('orderId'):
            logger.info(f"Position closed: {reason}")
            self.position = 0
            return True
        
        return False
    
    async def process_bar(self, bar: dict):
        """Process a new bar through strategy"""
        signal = self.strategy.add_bar(bar, source="projectx")
        
        if signal:
            if signal['action'] == 'entry':
                direction = Direction.LONG if signal['direction'] == 'long' else Direction.SHORT
                
                if await self.place_order(direction, signal['reason']):
                    self.position = 1 if direction == Direction.LONG else -1
                    self.position_entry_price = signal['price']
                    self.session_trades += 1
                    
                    logger.info(f"ENTRY: {signal['direction'].upper()} @ {signal['price']:.2f}")
                    logger.info(f"  Stop: {signal['stop']:.2f} | Target: {signal['target']:.2f}")
                    logger.info(f"  Reason: {signal['reason']}")
            
            elif signal['action'] == 'exit':
                if await self.close_position(signal['reason']):
                    pnl = signal['pnl_pts'] * INSTRUMENT['point_value'] * TRADING['contracts']
                    self.session_pnl += pnl
                    self.position = 0
                    
                    emoji = "✅" if pnl > 0 else "❌"
                    logger.info(f"{emoji} EXIT: {signal['direction'].upper()} @ {signal['exit_price']:.2f}")
                    logger.info(f"  P&L: {signal['pnl_pts']:.2f} pts (${pnl:.0f})")
                    logger.info(f"  Reason: {signal['reason']}")
                    logger.info(f"  Session P&L: ${self.session_pnl:.0f}")
    
    async def run_loop(self):
        """Main trading loop"""
        logger.info("Starting trading loop...")
        self.is_running = True
        
        last_bar_time = None
        
        while self.is_running:
            try:
                # Check RTH
                if not self.is_rth():
                    logger.debug("Outside RTH - waiting...")
                    await asyncio.sleep(60)
                    continue
                
                # Get latest bars
                df = await self.get_current_bars(50)
                
                if df.empty:
                    logger.warning("No bar data received")
                    await asyncio.sleep(30)
                    continue
                
                # Process new bars
                latest = df.iloc[-1]
                bar_time = latest['timestamp']
                
                if last_bar_time is None or bar_time > last_bar_time:
                    bar = {
                        'timestamp': bar_time,
                        'open': latest['open'],
                        'high': latest['high'],
                        'low': latest['low'],
                        'close': latest['close'],
                        'volume': latest['volume']
                    }
                    
                    await self.process_bar(bar)
                    last_bar_time = bar_time
                
                # Wait for next bar (5-min intervals)
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Trading loop stopped")
    
    async def run(self):
        """Main entry point"""
        logger.info("="*60)
        logger.info("DON FUTURES TOPSTEP - MNQ")
        logger.info(f"Mode: {self.mode.upper()}")
        logger.info("="*60)
        
        # Connect to ProjectX
        if not await self.connect_projectx():
            logger.error("Failed to connect - exiting")
            return
        
        # Show account balance (optional - may not be available)
        if self.account_id:
            try:
                balance = await self.projectx.get_account_balance(self.account_id)
                if balance and balance.get('balance'):
                    logger.info(f"Account Balance: ${balance.get('balance', 0):,.2f}")
                    logger.info(f"Available: ${balance.get('availableForTrading', 0):,.2f}")
            except Exception as e:
                logger.warning(f"Could not fetch balance (non-critical): {e}")
        
        # Start trading loop
        try:
            await self.run_loop()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.projectx:
                await self.projectx.disconnect()
    
    def stop(self):
        """Stop the bot"""
        self.is_running = False


async def main():
    parser = argparse.ArgumentParser(description='DON Futures TopStep Bot')
    parser.add_argument('--mode', choices=['shadow', 'live'], default='shadow',
                        help='Trading mode (shadow=paper, live=real)')
    args = parser.parse_args()
    
    bot = DONTradingBot(mode=args.mode)
    await bot.run()


if __name__ == '__main__':
    asyncio.run(main())
