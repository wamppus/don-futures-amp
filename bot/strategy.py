"""
DON Futures TopStep — RTH Only

Failed Test Entry Logic:
1. Track when price breaks channel (liquidity sweep)
2. If next bar closes back inside channel = failed test
3. Enter opposite direction (fade the trap)
4. Tight trailing stop to lock profits

TopStep Rules:
- RTH ONLY: 9:30 AM - 4:00 PM ET
- No overnight positions
- Flatten before 4:00 PM ET
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime, time
import pytz

from .logger import get_logger

# === CONSTANTS (no magic numbers) ===
MAX_BARS_CACHE = 200      # Max bars to keep in memory
WARMUP_BUFFER = 5         # Extra bars needed before trading
DEBUG_LOGGING = False     # Set True to enable verbose debug output


class Direction(Enum):
    LONG = 1
    SHORT = -1


class EntryType(Enum):
    BOUNCE = "bounce"
    FAILED_TEST = "failed_test"
    BREAKOUT = "breakout"


@dataclass
class DonFuturesConfig:
    """Strategy configuration — VALIDATED SETTINGS + TOPSTEP RTH"""
    
    # Channel period
    channel_period: int = 10
    channel_lag: int = 0  # Bars to lag channel calc (0=current, 5=5 bars ago)
    exit_period: int = 5
    
    # Entry types
    enable_bounce: bool = False        # Disabled by default
    enable_failed_test: bool = True    # PRIMARY EDGE
    enable_breakout: bool = False      # Disabled by default
    
    # Failed test tolerance (points)
    touch_tolerance_pts: float = 1.0
    
    # Breakout minimum (points)
    breakout_min_pts: float = 2.0
    
    # Risk management (points)
    stop_pts: float = 4.0
    target_pts: float = 4.0
    
    # Runner settings (adjusted for 1-min bars)
    use_runner: bool = True
    trail_activation_pts: float = 2.0   # Activate at +2 pts
    trail_distance_pts: float = 1.5     # Trail 1.5 pts behind
    
    # Time exit
    max_bars: int = 5
    
    # Contract specs
    tick_size: float = 0.25
    tick_value: float = 12.50  # ES = $12.50/tick, MES = $1.25/tick
    point_value: float = 50.0  # ES = $50/point, MES = $5/point
    
    # === TOPSTEP RTH SETTINGS ===
    rth_only: bool = True              # MUST be True for TopStep
    rth_start: time = time(9, 30)      # 9:30 AM ET
    rth_end: time = time(16, 0)        # 4:00 PM ET
    flatten_before_close: int = 5      # Flatten 5 min before close
    timezone: str = "America/New_York"
    
    # === TOPSTEP 100K RISK LIMITS ===
    daily_loss_limit: float = 1000.0   # Stop trading at $1K loss (50% of $2K limit)
    max_trades_per_day: int = 25       # Cap trades per session
    contracts: int = 2                 # Start with 2 MES
    account_size: str = "100K"         # TopStep account tier


# TOPSTEP 100K CONFIG — RTH ONLY, MES
VALIDATED_CONFIG = DonFuturesConfig(
    channel_period=10,
    enable_failed_test=True,
    enable_bounce=False,
    enable_breakout=False,
    trail_activation_pts=1.0,
    trail_distance_pts=0.5,
    stop_pts=4.0,
    target_pts=4.0,
    # MES contract specs (not ES)
    tick_size=0.25,
    tick_value=1.25,           # MES = $1.25/tick
    point_value=5.0,           # MES = $5/point (ES = $50)
    # RTH settings
    rth_only=True,
    rth_start=time(9, 30),
    rth_end=time(16, 0),
    flatten_before_close=5,
    # TopStep 100K limits
    daily_loss_limit=1000.0,   # 50% of $2K limit (safety buffer)
    max_trades_per_day=25,
    contracts=2,
    account_size="100K"
)


# Timezone for RTH calculations
ET = pytz.timezone("America/New_York")


@dataclass
class Position:
    """Active position tracking"""
    direction: Direction
    entry_type: EntryType
    entry_price: float
    entry_time: datetime
    entry_bar_idx: int
    stop: float
    target: float
    trail_stop: Optional[float] = None
    
    @property
    def effective_stop(self) -> float:
        if self.trail_stop is None:
            return self.stop
        if self.direction == Direction.LONG:
            return max(self.stop, self.trail_stop)
        else:
            return min(self.stop, self.trail_stop)


class DonFuturesStrategy:
    """
    Donchian Failed Test Strategy for ES/MES
    
    LOGS EVERYTHING — every bar, every signal, every state change.
    """
    
    def __init__(self, config: DonFuturesConfig = None, log_dir: str = "logs"):
        self.config = config or VALIDATED_CONFIG
        self.logger = get_logger(log_dir)
        
        self.bars: List[Dict] = []
        self.position: Optional[Position] = None
        self.bar_count: int = 0
        
        # Failed test detection state
        self.last_broke_high: bool = False
        self.last_broke_low: bool = False
        self.last_channel_high: float = 0
        self.last_channel_low: float = 0
        
        # Stats
        self.stats = {
            'signals': 0,
            'entries': 0,
            'exits': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0
        }
        
        # Daily risk tracking (TopStep limits)
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.current_trading_day: str = ""
        self.daily_limit_hit: bool = False
        
        self.logger.info(f"Strategy initialized with config:")
        self.logger.info(f"  Channel period: {self.config.channel_period}")
        self.logger.info(f"  Failed test: {self.config.enable_failed_test}")
        self.logger.info(f"  Trail: {self.config.trail_activation_pts}/{self.config.trail_distance_pts}")
        self.logger.info(f"  Stop/Target: {self.config.stop_pts}/{self.config.target_pts}")
        self.logger.info(f"  RTH Only: {self.config.rth_only}")
        self.logger.info(f"  RTH Window: {self.config.rth_start} - {self.config.rth_end} ET")
    
    def _is_rth(self, timestamp: datetime) -> bool:
        """Check if timestamp is within Regular Trading Hours (RTH)"""
        if not self.config.rth_only:
            return True
        
        # Handle timezone conversion
        if timestamp.tzinfo is None:
            # Naive datetime - check if it looks like ET or UTC
            # If hour is reasonable for ET market hours, assume ET
            # Otherwise assume UTC and convert
            if 6 <= timestamp.hour <= 20:
                # Likely already in ET (local time from Windows)
                current_time = timestamp.time()
                if DEBUG_LOGGING: self.logger.debug(f"RTH: Assuming ET (naive datetime): {current_time}")
            else:
                # Likely UTC, convert to ET
                timestamp = pytz.utc.localize(timestamp)
                et_time = timestamp.astimezone(ET)
                current_time = et_time.time()
                if DEBUG_LOGGING: self.logger.debug(f"RTH: Converted UTC to ET: {current_time}")
        else:
            et_time = timestamp.astimezone(ET)
            current_time = et_time.time()
            if DEBUG_LOGGING: self.logger.debug(f"RTH: Converted {timestamp.tzinfo} to ET: {current_time}")
        
        # Check if within RTH window
        return self.config.rth_start <= current_time < self.config.rth_end
    
    def _should_flatten(self, timestamp: datetime) -> bool:
        """Check if we should flatten before market close"""
        if not self.config.rth_only:
            return False
        
        # Convert to ET
        if timestamp.tzinfo is None:
            timestamp = pytz.utc.localize(timestamp)
        
        et_time = timestamp.astimezone(ET)
        current_time = et_time.time()
        
        # Flatten X minutes before close
        flatten_minutes = self.config.rth_end.hour * 60 + self.config.rth_end.minute - self.config.flatten_before_close
        flatten_hour = flatten_minutes // 60
        flatten_min = flatten_minutes % 60
        flatten_time = time(flatten_hour, flatten_min)
        
        return current_time >= flatten_time
    
    def _is_weekend(self, timestamp: datetime) -> bool:
        """Check if timestamp is on weekend (no trading)"""
        if timestamp.tzinfo is None:
            timestamp = pytz.utc.localize(timestamp)
        
        et_time = timestamp.astimezone(ET)
        # Monday = 0, Sunday = 6
        return et_time.weekday() >= 5
    
    def _get_trading_day(self, timestamp: datetime) -> str:
        """Get trading day string for daily limit tracking"""
        if timestamp.tzinfo is None:
            timestamp = pytz.utc.localize(timestamp)
        
        et_time = timestamp.astimezone(ET)
        return et_time.strftime("%Y-%m-%d")
    
    def _check_daily_limits(self) -> bool:
        """Check if we can take new trades (TopStep limits)"""
        # Already hit limit today
        if self.daily_limit_hit:
            return False
        
        # Check daily loss limit
        if self.daily_pnl <= -self.config.daily_loss_limit:
            self.daily_limit_hit = True
            self.logger.info(f"⚠️ DAILY LOSS LIMIT HIT: ${self.daily_pnl:.0f} - No more trades today")
            return False
        
        # Check max trades per day
        if self.daily_trades >= self.config.max_trades_per_day:
            self.daily_limit_hit = True
            self.logger.info(f"⚠️ MAX TRADES HIT: {self.daily_trades} trades - No more trades today")
            return False
        
        return True
    
    def add_bar(self, bar: Dict, source: str = "unknown") -> Optional[Dict]:
        """Process new bar and return signal if any."""
        self.bars.append(bar)
        self.bar_count += 1
        timestamp = bar.get('timestamp', datetime.now())
        
        self._log_bar(bar, timestamp, source)
        
        # RTH filtering: returns (should_continue, signal_or_none)
        should_continue, rth_signal = self._handle_rth(bar, timestamp)
        if not should_continue:
            return rth_signal
        
        self._reset_daily_stats_if_needed(timestamp)
        
        # Check if we have enough bars
        if not self._has_enough_bars():
            return None
        
        self._trim_old_bars()
        
        # Calculate channels
        channels = self._calculate_channels()
        if channels is None:
            return None
        ch_high, ch_low = channels
        
        # Check exits first, then entries
        if self.position:
            exit_signal = self._check_exit(bar, ch_high, ch_low)
            if exit_signal:
                return exit_signal
        else:
            entry_signal = self._check_entries(bar, ch_high, ch_low)
            if entry_signal:
                return entry_signal
        
        self._update_break_tracking(bar, ch_high, ch_low)
        self._log_position_state(bar)
        
        return None
    
    def _log_bar(self, bar: Dict, timestamp: datetime, source: str) -> None:
        """Log incoming bar data."""
        if DEBUG_LOGGING: 
            self.logger.debug(f"Bar #{self.bar_count}, ts={timestamp}, rth={self.config.rth_only}")
        self.logger.bar(
            str(timestamp),
            bar['open'], bar['high'], bar['low'], bar['close'],
            bar.get('volume', 0), source
        )
    
    def _handle_rth(self, bar: Dict, timestamp: datetime) -> tuple:
        """Handle RTH checks. Returns: (should_continue: bool, signal_or_none)."""
        if not self.config.rth_only:
            return True, None  # Continue processing
        
        if self._is_weekend(timestamp):
            self.logger.debug("Weekend - skipping")
            return False, None
        
        if self.position and self._should_flatten(timestamp):
            pnl = self._calc_position_pnl(bar['close'])
            self.logger.info("FLATTEN: Closing position before market close")
            return False, self._exit(bar['close'], pnl, 'rth_flatten', bar)
        
        is_rth = self._is_rth(timestamp)
        if DEBUG_LOGGING: 
            self.logger.debug(f"RTH check: ts={timestamp}, is_rth={is_rth}")
        
        if not is_rth:
            self.logger.debug("Outside RTH - skipping bar")
            self.last_broke_high = False
            self.last_broke_low = False
            return False, None
        
        return True, None  # Continue processing
    
    def _calc_position_pnl(self, current_price: float) -> float:
        """Calculate P&L for current position at given price."""
        if self.position.direction == Direction.LONG:
            return current_price - self.position.entry_price
        return self.position.entry_price - current_price
    
    def _reset_daily_stats_if_needed(self, timestamp: datetime) -> None:
        """Reset daily stats if new trading day."""
        trading_day = self._get_trading_day(timestamp)
        if trading_day != self.current_trading_day:
            if self.current_trading_day:
                self.logger.info(f"NEW DAY: Reset daily stats. Previous day P&L: ${self.daily_pnl:.0f}, Trades: {self.daily_trades}")
            self.current_trading_day = trading_day
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_limit_hit = False
    
    def _has_enough_bars(self) -> bool:
        """Check if we have enough bars for channel calculation."""
        min_bars_needed = self.config.channel_period + WARMUP_BUFFER
        if len(self.bars) < min_bars_needed:
            self.logger.debug(f"Warming up: {len(self.bars)}/{min_bars_needed} bars")
            return False
        return True
    
    def _trim_old_bars(self) -> None:
        """Trim old bars to prevent memory bloat."""
        if len(self.bars) > MAX_BARS_CACHE:
            self.bars = self.bars[-MAX_BARS_CACHE:]
    
    def _calculate_channels(self) -> Optional[tuple]:
        """Calculate Donchian channels. Returns (high, low) or None if not enough data."""
        lag = getattr(self.config, 'channel_lag', 0)
        end_idx = -(1 + lag)
        start_idx = end_idx - self.config.channel_period
        
        if abs(start_idx) > len(self.bars):
            if DEBUG_LOGGING: 
                self.logger.debug(f"Warming: have {len(self.bars)}, need {abs(start_idx)}")
            return None
        
        if DEBUG_LOGGING: 
            self.logger.debug(f"Processing: {len(self.bars)} bars, period={self.config.channel_period}, lag={lag}")
        
        channel_bars = self.bars[start_idx:end_idx or None]
        ch_high = max(b['high'] for b in channel_bars)
        ch_low = min(b['low'] for b in channel_bars)
        self.logger.channel(ch_high, ch_low, self.config.channel_period)
        
        return ch_high, ch_low
    
    def _update_break_tracking(self, bar: Dict, ch_high: float, ch_low: float) -> None:
        """Update channel break tracking for failed test detection."""
        tolerance = self.config.touch_tolerance_pts
        new_broke_high = bar['high'] > ch_high + tolerance
        new_broke_low = bar['low'] < ch_low - tolerance
        
        if DEBUG_LOGGING: 
            self.logger.debug(f"Break check: ch_low={ch_low:.2f}, bar_low={bar['low']:.2f}, broke={new_broke_low}")
        
        if new_broke_high and not self.last_broke_high:
            self.logger.break_detected("long", ch_high, bar['high'])
        if new_broke_low and not self.last_broke_low:
            self.logger.break_detected("short", ch_low, bar['low'])
        
        self.last_broke_high = new_broke_high
        self.last_broke_low = new_broke_low
        self.last_channel_high = ch_high
        self.last_channel_low = ch_low
    
    def _log_position_state(self, bar: Dict) -> None:
        """Log current position state if in a trade."""
        if self.position:
            unrealized = self._calc_unrealized_pnl(bar['close'])
            self.logger.position_state(
                True, self.position.direction.name.lower(),
                self.position.entry_price, self.position.effective_stop,
                unrealized
            )
    
    def _check_entries(self, bar: Dict, ch_high: float, ch_low: float) -> Optional[Dict]:
        """Check all entry conditions"""
        if DEBUG_LOGGING: self.logger.debug(f"Entry check: close={bar['close']:.2f}")
        
        # TopStep daily limits check
        daily_ok = self._check_daily_limits()
        if DEBUG_LOGGING: self.logger.debug(f"Daily: limit_hit={self.daily_limit_hit}, pnl=${self.daily_pnl:.0f}, trades={self.daily_trades}")
        if not daily_ok:
            return None
        
        tolerance = self.config.touch_tolerance_pts
        breakout_threshold = self.config.breakout_min_pts
        
        # === FAILED TEST (primary edge) ===
        if self.config.enable_failed_test:
            if DEBUG_LOGGING: self.logger.debug(f"Failed test: broke_high={self.last_broke_high}, broke_low={self.last_broke_low}, close={bar['close']:.2f}")
            
            # Broke high last bar, closed back below → SHORT
            if self.last_broke_high and bar['close'] < self.last_channel_high:
                reason = f"failed test: broke {self.last_channel_high:.2f}, reclaimed below"
                return self._enter(bar, Direction.SHORT, EntryType.FAILED_TEST, reason)
            
            # Broke low last bar, closed back above → LONG
            if self.last_broke_low and bar['close'] > self.last_channel_low:
                reason = f"failed test: broke {self.last_channel_low:.2f}, reclaimed above"
                return self._enter(bar, Direction.LONG, EntryType.FAILED_TEST, reason)
        
        # === BOUNCE ===
        if self.config.enable_bounce:
            # Touch high, reject → SHORT
            if (ch_high - tolerance <= bar['high'] <= ch_high + tolerance and 
                bar['close'] < ch_high - tolerance):
                reason = f"bounce reject at {ch_high:.2f}"
                return self._enter(bar, Direction.SHORT, EntryType.BOUNCE, reason)
            
            # Touch low, reject → LONG
            if (ch_low - tolerance <= bar['low'] <= ch_low + tolerance and
                bar['close'] > ch_low + tolerance):
                reason = f"bounce reject at {ch_low:.2f}"
                return self._enter(bar, Direction.LONG, EntryType.BOUNCE, reason)
        
        # === BREAKOUT ===
        if self.config.enable_breakout:
            # Break high → LONG
            if bar['close'] > ch_high + breakout_threshold:
                reason = f"breakout above {ch_high:.2f}"
                return self._enter(bar, Direction.LONG, EntryType.BREAKOUT, reason)
            
            # Break low → SHORT
            if bar['close'] < ch_low - breakout_threshold:
                reason = f"breakout below {ch_low:.2f}"
                return self._enter(bar, Direction.SHORT, EntryType.BREAKOUT, reason)
        
        return None
    
    def _enter(self, bar: Dict, direction: Direction, entry_type: EntryType, 
               reason: str) -> Dict:
        """Create position and return entry signal"""
        price = bar['close']
        
        if direction == Direction.LONG:
            stop = price - self.config.stop_pts
            target = price + self.config.target_pts
        else:
            stop = price + self.config.stop_pts
            target = price - self.config.target_pts
        
        self.position = Position(
            direction=direction,
            entry_type=entry_type,
            entry_price=price,
            entry_time=bar.get('timestamp', datetime.now()),
            entry_bar_idx=self.bar_count,
            stop=stop,
            target=target,
            trail_stop=None
        )
        
        self.stats['signals'] += 1
        self.stats['entries'] += 1
        
        # LOG IT
        self.logger.signal(entry_type.value, direction.name.lower(), price, reason, True)
        self.logger.entry(direction.name.lower(), entry_type.value, price, stop, target, reason)
        
        return {
            'action': 'entry',
            'direction': direction.name.lower(),
            'entry_type': entry_type.value,
            'price': price,
            'stop': stop,
            'target': target,
            'reason': reason,
            'timestamp': bar.get('timestamp')
        }
    
    def _check_exit(self, bar: Dict, ch_high: float, ch_low: float) -> Optional[Dict]:
        """Check exit conditions - NO LOOK-AHEAD BIAS
        
        Order matters! Check exits FIRST using trail from previous bar,
        THEN update trail for next bar.
        """
        position = self.position
        effective_stop = position.effective_stop
        is_long = position.direction == Direction.LONG
        
        # Direction-aware prices
        target_price = bar['high'] if is_long else bar['low']
        stop_price = bar['low'] if is_long else bar['high']
        
        # Target hit check
        target_hit = target_price >= position.target if is_long else target_price <= position.target
        if target_hit:
            return self._exit(position.target, self.config.target_pts, 'target', bar)
        
        # Stop hit check
        stop_hit = stop_price <= effective_stop if is_long else stop_price >= effective_stop
        if stop_hit:
            pnl = (effective_stop - position.entry_price) if is_long else (position.entry_price - effective_stop)
            reason = 'trail_stop' if position.trail_stop and effective_stop == position.trail_stop else 'stop'
            return self._exit(effective_stop, pnl, reason, bar)
        
        # Time exit
        bars_held = self.bar_count - position.entry_bar_idx
        if bars_held >= self.config.max_bars:
            pnl = self._calc_position_pnl(bar['close'])
            return self._exit(bar['close'], pnl, 'time', bar)
        
        # Update trailing stop for next bar
        self._update_trail_stop(bar, is_long)
        
        return None
    
    def _update_trail_stop(self, bar: Dict, is_long: bool) -> None:
        """Update trailing stop based on current bar's extremes."""
        if not self.config.use_runner:
            return
        
        position = self.position
        old_trail = position.trail_stop
        
        # Get the favorable price extreme
        extreme_price = bar['high'] if is_long else bar['low']
        profit = (extreme_price - position.entry_price) if is_long else (position.entry_price - extreme_price)
        
        if profit < self.config.trail_activation_pts:
            return
        
        # Calculate new trail
        if is_long:
            new_trail = extreme_price - self.config.trail_distance_pts
            should_update = position.trail_stop is None or new_trail > position.trail_stop
        else:
            new_trail = extreme_price + self.config.trail_distance_pts
            should_update = position.trail_stop is None or new_trail < position.trail_stop
        
        if should_update:
            position.trail_stop = new_trail
            self.logger.trail_update(old_trail or position.stop, new_trail, extreme_price)
    
    def _exit(self, exit_price: float, pnl_pts: float, reason: str, bar: Dict) -> Dict:
        """Close position and return exit signal"""
        p = self.position
        pnl_dollars = pnl_pts * self.config.point_value
        
        self.stats['exits'] += 1
        self.stats['total_pnl'] += pnl_pts
        if pnl_pts > 0:
            self.stats['wins'] += 1
        else:
            self.stats['losses'] += 1
        
        # Track daily stats for TopStep limits
        self.daily_pnl += pnl_dollars
        self.daily_trades += 1
        
        # LOG IT
        self.logger.exit(
            p.direction.name.lower(),
            p.entry_type.value,
            p.entry_price,
            exit_price,
            pnl_pts,
            pnl_dollars,
            reason
        )
        
        signal = {
            'action': 'exit',
            'direction': p.direction.name.lower(),
            'entry_type': p.entry_type.value,
            'entry_price': p.entry_price,
            'exit_price': exit_price,
            'pnl_pts': pnl_pts,
            'pnl_dollars': pnl_dollars,
            'reason': reason,
            'bars_held': self.bar_count - p.entry_bar_idx,
            'timestamp': bar.get('timestamp')
        }
        
        self.position = None
        return signal
    
    def _calc_unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L"""
        if not self.position:
            return 0.0
        if self.position.direction == Direction.LONG:
            return current_price - self.position.entry_price
        else:
            return self.position.entry_price - current_price
    
    def get_status(self) -> Dict[str, Any]:
        """Get current strategy status"""
        return {
            'in_position': self.position is not None,
            'direction': self.position.direction.name if self.position else None,
            'entry_type': self.position.entry_type.value if self.position else None,
            'entry_price': self.position.entry_price if self.position else None,
            'current_stop': self.position.effective_stop if self.position else None,
            'trail_active': self.position.trail_stop is not None if self.position else False,
            'stats': self.stats,
            'bars_loaded': len(self.bars)
        }
    
    def shutdown(self):
        """Clean shutdown with summary"""
        self.logger.session_summary()
