#!/usr/bin/env python3
"""
DON Futures Trading Engine

The bot IS the engine. It:
1. Fetches bars from ProjectX
2. Subscribes to live quotes for real-time exit monitoring
3. Runs strategy for entry signals at bar close
4. Monitors exits LIVE via quotes (no waiting for next bar)
5. Logs everything
6. Exposes state for GUI to read

GUI just displays what the engine is doing - it doesn't drive anything.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, time, timezone
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, asdict
from enum import Enum
import threading

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from .projectx_client import ProjectXClient
from .strategy import DonFuturesStrategy, DonFuturesConfig, Direction, Position, EntryType


ET = ZoneInfo('America/New_York')


@dataclass
class EngineState:
    """Current engine state - exposed for GUI"""
    is_running: bool = False
    is_connected: bool = False
    in_position: bool = False
    
    # Position info
    direction: Optional[str] = None
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    current_stop: float = 0.0
    current_target: float = 0.0
    trail_stop: Optional[float] = None
    unrealized_pnl: float = 0.0
    
    # Quote info
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    last_quote_time: Optional[datetime] = None
    
    # Channel info (for display)
    channel_high: float = 0.0
    channel_low: float = 0.0
    
    # Session stats
    signals: int = 0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    session_pnl: float = 0.0
    daily_pnl: float = 0.0
    
    # Last bar info
    last_bar_time: Optional[datetime] = None
    last_bar_close: float = 0.0


class TradingEngine:
    """
    The trading engine - runs independently, GUI just watches.
    
    Key design:
    - Bar processing happens on bar close (entry signals)
    - Exit monitoring happens LIVE via quotes (no bar delay)
    - channel_lag only affects DON channel calculation, nothing else
    """
    
    def __init__(self, username: str, api_key: str, config: Dict = None):
        self.username = username
        self.api_key = api_key
        self.config = config or {}
        
        # State
        self.state = EngineState()
        self._lock = threading.Lock()
        
        # Components
        self.client: Optional[ProjectXClient] = None
        self.strategy: Optional[DonFuturesStrategy] = None
        self.contract_id: Optional[str] = None
        
        # Bar tracking
        self.bars: List[Dict] = []
        self.last_bar_minute: Optional[datetime] = None
        
        # Build bars from quotes
        self.current_bar_minute: Optional[datetime] = None
        self.current_bar: Optional[Dict] = None  # {open, high, low, close, volume}
        
        # Position tracking (mirror of strategy position for quote monitoring)
        self.position: Optional[Position] = None
        
        # Callbacks for GUI
        self._on_log: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
        self._on_entry: Optional[Callable] = None
        self._on_exit: Optional[Callable] = None
        
        # Control
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Logging
        self.log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
    
    def set_callbacks(self, on_log=None, on_state_change=None, on_entry=None, on_exit=None):
        """Set callbacks for GUI updates"""
        self._on_log = on_log
        self._on_state_change = on_state_change
        self._on_entry = on_entry
        self._on_exit = on_exit
    
    def _log(self, message: str, level: str = 'info'):
        """Log message and notify GUI"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        
        # Write to file
        log_file = os.path.join(self.log_dir, f"engine_{datetime.now().strftime('%Y-%m-%d')}.log")
        with open(log_file, 'a') as f:
            f.write(log_line + '\n')
        
        # Notify GUI
        if self._on_log:
            self._on_log(message, level)
    
    def _update_state(self, **kwargs):
        """Update state and notify GUI"""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)
        
        if self._on_state_change:
            self._on_state_change(self.get_state())
    
    def get_state(self) -> Dict:
        """Get current state as dict"""
        with self._lock:
            return asdict(self.state)
    
    def update_config(self, config: Dict):
        """Update strategy config (can be called while running)"""
        self.config.update(config)
        
        if self.strategy:
            # Rebuild strategy config
            don_config = self._build_strategy_config()
            
            # Preserve state
            old_bars = self.strategy.bars
            old_broke_high = self.strategy.last_broke_high
            old_broke_low = self.strategy.last_broke_low
            old_ch_high = self.strategy.last_channel_high
            old_ch_low = self.strategy.last_channel_low
            
            # Recreate strategy
            self.strategy = DonFuturesStrategy(don_config, self.log_dir)
            self.strategy.bars = old_bars
            self.strategy.last_broke_high = old_broke_high
            self.strategy.last_broke_low = old_broke_low
            self.strategy.last_channel_high = old_ch_high
            self.strategy.last_channel_low = old_ch_low
            
            self._log(f"Config updated: Stop={don_config.stop_pts}, Target={don_config.target_pts}")
    
    def _build_strategy_config(self) -> DonFuturesConfig:
        """Build strategy config from self.config"""
        return DonFuturesConfig(
            channel_period=self.config.get('lookback_bars', 10),
            channel_lag=self.config.get('channel_lag', 0),  # ONLY affects channel calc
            enable_failed_test=True,
            enable_bounce=False,
            enable_breakout=self.config.get('enable_breakout', True),
            touch_tolerance_pts=self.config.get('sr_touch_tolerance', 1.0),
            stop_pts=self.config.get('stop_pts', 4.0),
            target_pts=self.config.get('target_pts', 4.0),
            use_runner=self.config.get('use_trailing_stop', True),
            trail_activation_pts=self.config.get('trail_activation_pts', 2.0),
            trail_distance_pts=self.config.get('trail_distance', 1.5),
            max_bars=self.config.get('max_hold_bars', 5),
            tick_size=0.25,
            tick_value=0.50,  # MNQ
            point_value=2.0,  # MNQ
            rth_only=True,
            daily_loss_limit=self.config.get('daily_loss_limit', 1000.0),
            max_trades_per_day=self.config.get('max_trades_per_day', 25),
        )
    
    def _on_quote(self, quote_data: Dict):
        """
        Handle incoming quote - builds bars AND monitors exits in real-time.
        """
        try:
            bid = quote_data.get('bid')
            ask = quote_data.get('ask')
            
            # Skip bad quotes (None or 0 values)
            if bid is None or ask is None or bid == 0 or ask == 0:
                return
            
            mid = (bid + ask) / 2
            now = datetime.now(timezone.utc)
            
            # Update state
            self._update_state(
                bid=bid,
                ask=ask,
                mid=mid,
                last_quote_time=now
            )
            
            # === BUILD BARS FROM QUOTES ===
            self._update_bar_from_quote(mid, now)
            
            # === REAL-TIME EXIT MONITORING ===
            if self.position:
                self._check_live_exit(mid, now)
        
        except Exception as e:
            print(f"[QUOTE-ERROR] {e}")
    
    def _update_bar_from_quote(self, price: float, timestamp: datetime):
        """Build 1-minute bars from quote stream"""
        # Get current minute (truncate to minute boundary)
        bar_minute = timestamp.replace(second=0, microsecond=0)
        
        # Convert to ET for strategy
        bar_minute_et = bar_minute.astimezone(ET).replace(tzinfo=None)
        
        # New minute? Emit previous bar and start new one
        if self.current_bar_minute is not None and bar_minute > self.current_bar_minute:
            # Emit completed bar
            if self.current_bar and self.strategy:
                completed_bar = {
                    'timestamp': self.current_bar_minute.astimezone(ET).replace(tzinfo=None),
                    'open': self.current_bar['open'],
                    'high': self.current_bar['high'],
                    'low': self.current_bar['low'],
                    'close': self.current_bar['close'],
                    'volume': self.current_bar.get('volume', 0)
                }
                self._log(f"Bar: {completed_bar['timestamp'].strftime('%H:%M')} | O={completed_bar['open']:.2f} H={completed_bar['high']:.2f} L={completed_bar['low']:.2f} C={completed_bar['close']:.2f}")
                
                # Process bar through strategy
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._process_bar(completed_bar),
                        self._loop
                    )
            
            # Start new bar
            self.current_bar_minute = bar_minute
            self.current_bar = {
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1
            }
        elif self.current_bar_minute is None:
            # First quote - start first bar
            self.current_bar_minute = bar_minute
            self.current_bar = {
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1
            }
        else:
            # Same minute - update OHLC
            if self.current_bar:
                self.current_bar['high'] = max(self.current_bar['high'], price)
                self.current_bar['low'] = min(self.current_bar['low'], price)
                self.current_bar['close'] = price
                self.current_bar['volume'] += 1
    
    def _check_live_exit(self, price: float, timestamp: datetime):
        """
        Check if price has hit stop or target - LIVE, not waiting for bar.
        
        This is the key fix: exits happen when price crosses level,
        not when the next bar closes.
        """
        if not self.position:
            return
        
        p = self.position
        eff_stop = p.effective_stop
        
        exit_price = None
        exit_reason = None
        
        if p.direction == Direction.LONG:
            # Target hit
            if price >= p.target:
                exit_price = p.target
                exit_reason = 'target'
            # Stop hit
            elif price <= eff_stop:
                exit_price = eff_stop
                exit_reason = 'trail_stop' if (p.trail_stop and eff_stop == p.trail_stop) else 'stop'
        
        else:  # SHORT
            # Target hit
            if price <= p.target:
                exit_price = p.target
                exit_reason = 'target'
            # Stop hit
            elif price >= eff_stop:
                exit_price = eff_stop
                exit_reason = 'trail_stop' if (p.trail_stop and eff_stop == p.trail_stop) else 'stop'
        
        if exit_price:
            self._execute_exit(exit_price, exit_reason, timestamp, source='quote')
    
    def _update_trail_stop(self, price: float):
        """Update trailing stop based on current price"""
        if not self.position or not self.strategy.config.use_runner:
            return
        
        p = self.position
        cfg = self.strategy.config
        
        if p.direction == Direction.LONG:
            profit = price - p.entry_price
            if profit >= cfg.trail_activation_pts:
                new_trail = price - cfg.trail_distance_pts
                if p.trail_stop is None or new_trail > p.trail_stop:
                    old = p.trail_stop
                    p.trail_stop = new_trail
                    self._log(f"Trail stop updated: {old or p.stop:.2f} -> {new_trail:.2f}")
        else:
            profit = p.entry_price - price
            if profit >= cfg.trail_activation_pts:
                new_trail = price + cfg.trail_distance_pts
                if p.trail_stop is None or new_trail < p.trail_stop:
                    old = p.trail_stop
                    p.trail_stop = new_trail
                    self._log(f"Trail stop updated: {old or p.stop:.2f} -> {new_trail:.2f}")
        
        # Update state
        self._update_state(
            current_stop=p.effective_stop,
            trail_stop=p.trail_stop
        )
    
    def _execute_exit(self, exit_price: float, reason: str, timestamp: datetime, source: str = 'bar'):
        """Execute exit and update all state"""
        if not self.position:
            return
        
        p = self.position
        
        # Calculate P&L
        if p.direction == Direction.LONG:
            pnl_pts = exit_price - p.entry_price
        else:
            pnl_pts = p.entry_price - exit_price
        
        pnl_dollars = pnl_pts * self.strategy.config.point_value
        
        # Update stats
        with self._lock:
            self.state.trades += 1
            self.state.session_pnl += pnl_dollars
            self.state.daily_pnl += pnl_dollars
            if pnl_pts > 0:
                self.state.wins += 1
            else:
                self.state.losses += 1
        
        # Log
        emoji = '+' if pnl_pts > 0 else 'X'
        self._log(
            f"{emoji} EXIT ({source}): {p.direction.name} @ {exit_price:.2f} | "
            f"PnL: {pnl_pts:+.2f} pts (${pnl_dollars:+.0f}) | Reason: {reason}",
            'exit_win' if pnl_pts > 0 else 'exit_loss'
        )
        
        # Log to trades file
        self._log_trade(p, exit_price, pnl_pts, pnl_dollars, reason, timestamp)
        
        # Clear position
        self.position = None
        if self.strategy:
            self.strategy.position = None
        
        # Update state
        self._update_state(
            in_position=False,
            direction=None,
            entry_price=0.0,
            current_stop=0.0,
            current_target=0.0,
            trail_stop=None,
            unrealized_pnl=0.0
        )
        
        # Notify GUI
        if self._on_exit:
            self._on_exit({
                'direction': p.direction.name,
                'entry_price': p.entry_price,
                'exit_price': exit_price,
                'pnl_pts': pnl_pts,
                'pnl_dollars': pnl_dollars,
                'reason': reason,
                'source': source
            })
    
    def _log_trade(self, position: Position, exit_price: float, pnl_pts: float, 
                   pnl_dollars: float, reason: str, exit_time: datetime):
        """Log trade to JSONL file"""
        trade = {
            'timestamp': exit_time.isoformat(),
            'direction': position.direction.name,
            'entry_type': position.entry_type.value,
            'entry_price': position.entry_price,
            'entry_time': position.entry_time.isoformat() if position.entry_time else None,
            'exit_price': exit_price,
            'exit_time': exit_time.isoformat(),
            'pnl_pts': pnl_pts,
            'pnl_dollars': pnl_dollars,
            'reason': reason
        }
        
        trades_file = os.path.join(self.log_dir, 'trades.jsonl')
        with open(trades_file, 'a') as f:
            f.write(json.dumps(trade) + '\n')
    
    async def _process_bar(self, bar: Dict):
        """
        Process a completed bar through strategy.
        
        This handles ENTRY signals only. Exits are monitored live via quotes.
        """
        # Add to our bar history
        self.bars.append(bar)
        if len(self.bars) > 200:
            self.bars = self.bars[-200:]
        
        # Update state
        self._update_state(
            last_bar_time=bar['timestamp'],
            last_bar_close=bar['close']
        )
        
        # Update trail stop based on bar high/low
        if self.position:
            if self.position.direction == Direction.LONG:
                self._update_trail_stop(bar['high'])
            else:
                self._update_trail_stop(bar['low'])
            
            # Update unrealized P&L
            if self.position.direction == Direction.LONG:
                unrealized = bar['close'] - self.position.entry_price
            else:
                unrealized = self.position.entry_price - bar['close']
            self._update_state(unrealized_pnl=unrealized)
        
        # Run strategy for entry signals
        signal = self.strategy.add_bar(bar, source="engine")
        
        if signal:
            print(f"[ENGINE] Got signal from strategy: {signal['action']} - {signal.get('direction', 'N/A')}")
        
        # Update channel display
        if len(self.strategy.bars) >= self.strategy.config.channel_period + 1:
            lag = self.strategy.config.channel_lag
            end_idx = -(1 + lag)
            start_idx = end_idx - self.strategy.config.channel_period
            if abs(start_idx) <= len(self.strategy.bars):
                channel_bars = self.strategy.bars[start_idx:end_idx or None]
                ch_high = max(b['high'] for b in channel_bars)
                ch_low = min(b['low'] for b in channel_bars)
                self._update_state(channel_high=ch_high, channel_low=ch_low)
        
        if signal:
            if signal['action'] == 'entry':
                self._handle_entry(signal, bar)
            elif signal['action'] == 'exit':
                # Strategy detected exit (time exit, RTH flatten) - execute it
                self._execute_exit(
                    signal['exit_price'],
                    signal['reason'],
                    bar.get('timestamp', datetime.now(timezone.utc)),
                    source='bar'
                )
    
    def _handle_entry(self, signal: Dict, bar: Dict):
        """Handle entry signal from strategy"""
        print(f"[ENGINE] _handle_entry called: {signal['direction']} @ {signal['price']}")
        
        # Create position
        direction = Direction.LONG if signal['direction'] == 'long' else Direction.SHORT
        entry_type = EntryType(signal['entry_type'])
        
        self.position = Position(
            direction=direction,
            entry_type=entry_type,
            entry_price=signal['price'],
            entry_time=bar.get('timestamp', datetime.now(timezone.utc)),
            entry_bar_idx=len(self.bars),
            stop=signal['stop'],
            target=signal['target'],
            trail_stop=None
        )
        
        # Update strategy's position reference too
        self.strategy.position = self.position
        
        # Update state
        with self._lock:
            self.state.signals += 1
        
        self._update_state(
            in_position=True,
            direction=direction.name,
            entry_price=signal['price'],
            entry_time=bar.get('timestamp'),
            current_stop=signal['stop'],
            current_target=signal['target'],
            trail_stop=None,
            unrealized_pnl=0.0
        )
        
        # Log
        self._log(
            f">> ENTRY: {signal['direction'].upper()} @ {signal['price']:.2f} | "
            f"Stop: {signal['stop']:.2f} | Target: {signal['target']:.2f} | "
            f"Reason: {signal['reason']}",
            'entry'
        )
        
        # Notify GUI
        if self._on_entry:
            self._on_entry(signal)
    
    async def _run_loop(self):
        """Main engine loop"""
        self._log("Engine starting...")
        
        # Connect to ProjectX
        self.client = ProjectXClient(self.username, self.api_key)
        
        if not await self.client.connect():
            self._log("Failed to connect to ProjectX", 'error')
            return
        
        self._update_state(is_connected=True)
        self._log("Connected to ProjectX")
        
        # Find MNQ contract
        contract = await self.client.find_mnq_contract()
        if not contract:
            self._log("Could not find MNQ contract", 'error')
            return
        
        self.contract_id = contract['id']
        self._log(f"Trading: {contract.get('description', self.contract_id)}")
        self._log(f"Contract ID: {self.contract_id}, Symbol: {contract.get('symbolId')}")
        
        # Initialize strategy
        self.strategy = DonFuturesStrategy(self._build_strategy_config(), self.log_dir)
        
        # Subscribe to quotes for REAL-TIME exit monitoring
        try:
            await self.client.subscribe_quotes(self.contract_id, self._on_quote)
            self._log("Subscribed to live quotes (real-time exit monitoring)")
        except Exception as e:
            self._log(f"Quote subscription failed: {e}", 'error')
        
        self._update_state(is_running=True)
        
        # Main loop - bars are built from quotes, just keep alive
        self._log("Building bars from quote stream...")
        while self._running:
            try:
                # Just keep the connection alive - bars built from quotes in _update_bar_from_quote
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Error in main loop: {e}", 'error')
                await asyncio.sleep(10)
        
        # Cleanup
        if self.client:
            await self.client.disconnect()
        
        self._update_state(is_running=False, is_connected=False)
        self._log("Engine stopped")
    
    def start(self):
        """Start the engine in a background thread"""
        if self._running:
            return
        
        self._running = True
        
        def run_in_thread():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run_loop())
            finally:
                self._loop.close()
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
    
    def stop(self):
        """Stop the engine"""
        self._running = False
        self._log("Stop requested...")
