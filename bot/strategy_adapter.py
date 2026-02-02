"""
Strategy Adapter - Wraps DON strategy to match v3 GUI interface
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from .strategy import DonFuturesStrategy, DonFuturesConfig, Direction as DONDirection, VALIDATED_CONFIG


class Direction(Enum):
    LONG = 1
    SHORT = -1


@dataclass
class Quote:
    bid: float
    ask: float
    last: float
    timestamp: datetime
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class DONStrategyAdapter:
    """
    Adapter to make DON strategy compatible with v3 GUI
    """
    
    def __init__(self, config: dict = None):
        # Build DON config from dict
        # Maps v3 GUI config keys to DON strategy params
        self.config = config or {}
        
        # DON strategy only uses these settings (ignores CT filter, trend filter, RSI, etc)
        don_config = DonFuturesConfig(
            # Channel period = lookback_bars in v3 GUI
            channel_period=self.config.get('lookback_bars', self.config.get('channel_period', 10)),
            channel_lag=self.config.get('channel_lag', 0),
            enable_failed_test=True,
            enable_bounce=False,
            enable_breakout=False,
            # Touch tolerance = sr_touch_tolerance in v3 GUI
            touch_tolerance_pts=self.config.get('sr_touch_tolerance', self.config.get('touch_tolerance', 1.0)),
            stop_pts=self.config.get('stop_pts', 4.0),
            target_pts=self.config.get('target_pts', 4.0),
            # Runner = use_trailing_stop in v3 GUI
            use_runner=self.config.get('use_trailing_stop', self.config.get('use_runner', True)),
            trail_activation_pts=self.config.get('trail_activation_pts', 1.0),
            trail_distance_pts=self.config.get('trail_distance', 0.5),
            max_bars=self.config.get('max_hold_bars', 5),
            tick_size=0.25,
            tick_value=0.50,  # MNQ
            point_value=2.0,   # MNQ
            rth_only=True,
            daily_loss_limit=self.config.get('daily_loss_limit', 1000.0),
            max_trades_per_day=self.config.get('max_trades_per_day', 25),
        )
        
        # Log what settings are actually being used
        print(f"[DON] Channel: {don_config.channel_period}, Stop: {don_config.stop_pts}, Target: {don_config.target_pts}")
        print(f"[DON] Trail: {don_config.trail_activation_pts}/{don_config.trail_distance_pts}, Runner: {don_config.use_runner}")
        
        self.strategy = DonFuturesStrategy(don_config, "logs")
        self.current_quote: Optional[Quote] = None
        
        # Track position for GUI
        self.position = 0
        self.entry_price = 0.0
        self.pending_signal = None
    
    def update_config(self, config: dict):
        """Update strategy config and recreate strategy with new settings"""
        self.config.update(config)
        
        # Recreate strategy with new config
        don_config = DonFuturesConfig(
            channel_period=self.config.get('lookback_bars', self.config.get('channel_period', 10)),
            channel_lag=self.config.get('channel_lag', 0),
            enable_failed_test=True,
            enable_bounce=False,
            enable_breakout=False,
            touch_tolerance_pts=self.config.get('sr_touch_tolerance', self.config.get('touch_tolerance', 1.0)),
            stop_pts=self.config.get('stop_pts', 4.0),
            target_pts=self.config.get('target_pts', 4.0),
            use_runner=self.config.get('use_trailing_stop', self.config.get('use_runner', True)),
            trail_activation_pts=self.config.get('trail_activation_pts', 2.0),
            trail_distance_pts=self.config.get('trail_distance', 1.5),
            max_bars=self.config.get('max_hold_bars', 5),
            tick_size=0.25,
            tick_value=0.50,
            point_value=2.0,
            rth_only=True,
            daily_loss_limit=self.config.get('daily_loss_limit', 1000.0),
            max_trades_per_day=self.config.get('max_trades_per_day', 25),
        )
        
        # Keep existing bars AND state when recreating strategy
        old_bars = self.strategy.bars if self.strategy else []
        old_last_broke_high = self.strategy.last_broke_high if self.strategy else False
        old_last_broke_low = self.strategy.last_broke_low if self.strategy else False
        old_last_ch_high = self.strategy.last_channel_high if self.strategy else 0
        old_last_ch_low = self.strategy.last_channel_low if self.strategy else 0
        
        self.strategy = DonFuturesStrategy(don_config)
        self.strategy.bars = old_bars
        self.strategy.last_broke_high = old_last_broke_high
        self.strategy.last_broke_low = old_last_broke_low
        self.strategy.last_channel_high = old_last_ch_high
        self.strategy.last_channel_low = old_last_ch_low
        
        print(f"[DON] Config updated - Stop: {don_config.stop_pts}, Target: {don_config.target_pts}")
    
    def set_quote(self, quote: Quote):
        """Set current quote"""
        self.current_quote = quote
    
    def add_historical_bar(self, bar: dict):
        """Add historical bar for warmup"""
        self.strategy.add_bar(bar, source="historical")
    
    def on_bar(self, bar: dict) -> dict:
        """
        Process a new bar and return events dict
        
        Returns dict with keys:
        - 'stale': bool - True if bar was historical/stale
        - 'signal': Signal object or None
        - 'entry': Trade object or None  
        - 'exit': Trade object or None
        """
        result = {
            'stale': False,
            'signal': None,
            'entry': None,
            'exit': None
        }
        
        # Debug: Show channel levels (with lag, matching strategy calc)
        strat = self.strategy
        lag = getattr(strat.config, 'channel_lag', 0)
        min_bars = strat.config.channel_period + lag + 1
        if len(strat.bars) >= min_bars:
            end_idx = -(1 + lag)
            start_idx = end_idx - strat.config.channel_period
            channel_bars = strat.bars[start_idx:end_idx or None]
            ch_high = max(b['high'] for b in channel_bars)
            ch_low = min(b['low'] for b in channel_bars)
            print(f"[CHANNEL] High={ch_high:.2f}, Low={ch_low:.2f}, Bar close={bar['close']:.2f}, "
                  f"Broke H={strat.last_broke_high}, Broke L={strat.last_broke_low}")
        
        signal = self.strategy.add_bar(bar, source="live")
        
        if signal:
            if signal['action'] == 'entry':
                # Convert to GUI event format
                dir_enum = Direction.LONG if signal['direction'] == 'long' else Direction.SHORT
                
                # Create signal object
                result['signal'] = type('Signal', (), {
                    'direction': dir_enum,
                    'sr_level': signal.get('sr_level', signal['price']),
                    'entry_price': signal['price'],
                    'stop_price': signal['stop'],
                    'target_price': signal['target'],
                })()
                
                # Create entry/trade object
                result['entry'] = type('Trade', (), {
                    'direction': dir_enum,
                    'entry_price': signal['price'],
                    'stop_price': signal['stop'],
                    'target_price': signal['target'],
                    'sr_level': signal.get('sr_level', signal['price']),
                })()
                
                self.position = 1 if signal['direction'] == 'long' else -1
                self.entry_price = signal['price']
                
            elif signal['action'] == 'exit':
                dir_enum = Direction.LONG if signal['direction'] == 'long' else Direction.SHORT
                
                # Create exit reason enum-like object
                exit_reason = type('ExitReason', (), {'value': signal['reason']})()
                
                result['exit'] = type('Trade', (), {
                    'direction': dir_enum,
                    'entry_price': self.entry_price,
                    'exit_price': signal['exit_price'],
                    'stop_price': signal.get('stop', 0),
                    'target_price': signal.get('target', 0),
                    'sr_level': signal.get('sr_level', 0),
                    'pnl_pts': signal['pnl_pts'],
                    'pnl_dollars': signal.get('pnl_dollars', signal['pnl_pts'] * 2.0),
                    'exit_reason': exit_reason,
                    'entry_time': signal.get('entry_time'),
                    'exit_time': signal.get('exit_time'),
                    'bars_held': signal.get('bars_held', 0),
                })()
                
                self.position = 0
                self.entry_price = 0.0
        
        return result
    
    def get_stats(self) -> dict:
        """Get strategy statistics"""
        status = self.strategy.get_status()
        return {
            'signals': status['stats']['signals'],
            'trades': status['stats']['exits'],
            'wins': status['stats']['wins'],
            'losses': status['stats']['losses'],
            'pnl': status['stats']['total_pnl'],
            'win_rate': status['stats']['wins'] / max(1, status['stats']['exits']) * 100,
            'in_position': status['in_position'],
            'direction': status['direction'],
            'entry_price': status['entry_price'],
        }
    
    def get_position(self) -> dict:
        """Get current position info"""
        status = self.strategy.get_status()
        return {
            'in_position': status['in_position'],
            'direction': status['direction'],
            'entry_price': status['entry_price'],
            'current_stop': status['current_stop'],
        }
